import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { errorText, fmtTime } from "../api";
import { LocalFiles } from "../components/LocalFiles";
import { ScriptDrop } from "../components/ScriptDrop";
import { ExampleSelect, FileDrop, linkedRow, Picked, StyleSelect, UploadRow } from "../components/studioParts";
import { Banner, Dialog, Disclosure, Icon, LoadingPage, PageHead, Toggle, toast, usePoll } from "../components/ui";
import { PlanForm, PlanSheet, useChanged } from "../components/VideoPlan";
import { useAppearance } from "../prefs";
import { navigate, redirect, useLeaveGuard } from "../router";
import { Asset, PlanFields, Script, SetupFile, SetupMessage, SetupMode, SetupQuestion, studio, uploadIds, VideoSetup } from "../studio";
import "../videoSetup.css";

const ACCEPT = "video/*,image/png,image/jpeg,image/webp,audio/*,.mkv,.m4v,.flac,.opus,.ogg";
const MODES: { value: SetupMode; title: string; about: string }[] = [
  { value: "ask", title: "Ask me questions",
    about: "ClipForge AI shows you a plan and asks a few short questions when it needs to. Then you build." },
  { value: "auto", title: "Just do it",
    about: "No questions: it plans from what you said and starts editing right away. You can change everything after." },
];

/** Make a YouTube video (docs/clipforge/VIDEO_SETUP.md): drop in your files and tell ClipForge AI your idea, plan it
 * together (or let it just do it), then build. From the first message the video is a draft in Projects, so leaving
 * keeps the files, the conversation and the plan. */
export default function MakeVideo({ id }: { id: string }) {
  return id ? <Planning id={id} /> : <Start />;
}

/** An idea handed over in the link (ClipForge AI's "Make a YouTube video" button: #/create/video?idea=…). */
function ideaFromLink(): string {
  const raw = window.location.hash;
  const q = raw.indexOf("?");
  return q < 0 ? "" : (new URLSearchParams(raw.slice(q + 1)).get("idea") || "").slice(0, 4000);
}

/** What the model setting means for this page, in one line. */
function ModelLine({ model }: { model: VideoSetup["model"] | null }) {
  if (!model) return null;
  return model.ready
    ? <p className="small muted">ClipForge AI uses {model.label}{model.local ? ", on this computer" : ", over the internet"}. It reads text only: your idea, the conversation, the plan so far, your file names, what is said in your videos, {model.brain === false ? "know-how and helper notes (never your Brain notes)" : "your Brain rules, and the memories, know-how and helper notes that fit your idea"}. <a href="#/settings/ai">Change</a></p>
    : <p className="small muted">ClipForge AI has no model yet, so its built-in rules read what you say (lengths, shapes, feel, music, captions, what to keep or cut, how it opens). <a href="#/settings/ai">Set up the free built-in model</a> to talk about anything.</p>;
}

// ------------------------------------------------------------------ the start: your files and your idea
function Start() {
  const { appearance, set: setAppearance } = useAppearance();
  const [files, setFiles] = useState<Picked[]>([]);
  const [linked, setLinked] = useState<Picked[]>([]);
  const [order, setOrder] = useState<string[]>([]);
  const [local, setLocal] = useState<"unknown" | "yes" | "no">("unknown");
  const [browsing, setBrowsing] = useState(false);
  const [dragging, setDragging] = useState<string | null>(null);
  const [idea, setIdea] = useState(ideaFromLink);
  const [mode, setMode] = useState<SetupMode | null>(null);  // null: as last time
  const [style, setStyle] = useState("saved");
  const [example, setExample] = useState("");
  const [script, setScript] = useState<Script | null>(null);
  const [name, setName] = useState("");
  const [remember, setRemember] = useState<boolean | null>(null);  // null: your Customize choice
  const [styleName, setStyleName] = useState("");
  const [model, setModel] = useState<VideoSetup["model"] | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const removed = useRef(new Set<string>());  // taken out: an upload still finishing does not bring it back

  useEffect(() => {
    let alive = true;
    studio.setupModel().then((m) => alive && setModel(m)).catch(() => alive && setModel(null));
    // "Add from this computer" exists on the desktop only (the cloud answers 403)
    studio.localBrowse("").then(() => alive && setLocal("yes")).catch(() => alive && setLocal("no"));
    return () => { alive = false; };
  }, []);

  const chosen: SetupMode = mode ?? (appearance.video_setup_mode === "auto" ? "auto" : "ask");
  const remembering = remember ?? appearance.remember_style;
  const byKey = Object.fromEntries([...files, ...linked].map((f) => [f.key, f]));
  const ordered = order.map((k) => byKey[k]).filter(Boolean);
  const uploading = ordered.some((f) => !f.asset);
  const ready = ordered.length > 0 && !uploading && ordered.some((f) => f.asset?.kind === "video");
  const move = (key: string, by: number) => setOrder((o) => {
    const i = o.indexOf(key);
    const j = Math.max(0, Math.min(o.length - 1, i + by));
    const next = [...o];
    next.splice(i, 1);
    next.splice(j, 0, key);
    return next;
  });
  const addLinked = (assets: Asset[]) => {
    const rows = assets.map(linkedRow);
    rows.forEach((r) => removed.current.delete(r.key));
    setLinked((l) => [...l, ...rows.filter((r) => !l.some((x) => x.key === r.key))]);
    setOrder((o) => [...o, ...rows.map((r) => r.key).filter((k) => !o.includes(k))]);
  };

  const submit = async () => {
    setBusy(true);
    setProblem("");
    try {
      const v = await studio.startVideoSetup({
        asset_ids: ordered.map((f) => f.asset!.id), upload_ids: uploadIds(ordered.map((f) => f.asset)), idea: idea.trim(),
        mode: chosen, name: name.trim(), style_id: style,
        reference_id: example, script, remember: { enabled: remembering, name: styleName.trim() } });
      if (chosen !== appearance.video_setup_mode) setAppearance({ video_setup_mode: chosen });  // for next time
      navigate(v.href);
    } catch (e) {
      setProblem(errorText(e));
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <PageHead kind="Make" title="Make a YouTube video" crumbs={[{ label: "Home", href: "#/" }, { label: "Make a YouTube video" }]}
        sub="Drop in your clips, pictures and sounds, tell ClipForge AI your idea, and it plans and edits the video with you." />
      <div className="studio-grid">
        <div className="stack-5">
          <section className="panel" aria-labelledby="vs-files-h">
            <h2 id="vs-files-h">Your files</h2>
            <FileDrop accept={ACCEPT} multiple label="Drop videos, pictures and sounds here (as many as you like)"
              onPicked={(keys) => keys.forEach((k) => removed.current.delete(k))}
              onAssets={(rows) => { setFiles(rows); setOrder((o) => [...o.filter((k) => k.startsWith("linked|") || rows.some((r) => r.key === k)),
                ...rows.map((r) => r.key).filter((k) => !o.includes(k) && !removed.current.has(k))]); }} />
            {local === "yes" && !browsing && <button type="button" className="btn local-pick" onClick={() => setBrowsing(true)}><Icon name="folder" />Add from this computer (big files, nothing is copied)</button>}
            {browsing && <LocalFiles onLinked={addLinked} onClose={() => setBrowsing(false)} />}
            {ordered.length > 1 && <p className="small muted">Videos and pictures start in this order. ClipForge AI listens to every video as soon as you start, so it knows what is said in them while you plan.</p>}
            <ol className="file-list" aria-label="Your files in order">
              {ordered.map((f, i) => (
                <li key={f.key} draggable onDragStart={() => setDragging(f.key)} onDragEnd={() => setDragging(null)}
                  onDragOver={(e) => e.preventDefault()} onDrop={() => dragging && dragging !== f.key && move(dragging, order.indexOf(f.key) - order.indexOf(dragging))}
                  className={dragging === f.key ? "dragging" : ""}>
                  <UploadRow row={f} extra={<>
                    <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${f.file.name} up`} disabled={i === 0} onClick={() => move(f.key, -1)}><Icon name="chev" className="vs-up" /></button>
                    <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${f.file.name} down`} disabled={i === ordered.length - 1} onClick={() => move(f.key, 1)}><Icon name="chev" className="vs-down" /></button>
                    <button type="button" className="btn btn-small btn-icon" aria-label={`Remove ${f.file.name}`} onClick={() => {
                      removed.current.add(f.key);
                      f.forget?.();  // its upload stops and it leaves the drop's list too (picking it again starts over)
                      setOrder((o) => o.filter((k) => k !== f.key));
                    }}><Icon name="x" /></button>
                  </>} />
                </li>
              ))}
            </ol>
          </section>
        </div>
        <div className="stack-5">
          <section className="panel vs-idea" aria-labelledby="vs-idea-h">
            <h2 id="vs-idea-h">Your idea</h2>
            <label className="field"><span>Tell ClipForge AI about the video, in your own words</span>
              <textarea value={idea} maxLength={4000} onChange={(e) => setIdea(e.target.value)}
                placeholder="For example: our lake weekend for the family, about 10 minutes, calm. Start with the jump off the dock, then the drive up, swimming, and the sunset at the end. Use my summer song as the music." /></label>
            <p className="hint">What happens, who it's for, how long, the feel, how it should open, the story in order, what to keep or cut, the music. As much or as little as you like: you can keep talking to it after this.</p>
            <fieldset className="stack-2"><legend className="label">How should ClipForge AI work?</legend>
              <div className="mode-pick vs-modes">
                {MODES.map((m) => (
                  <label key={m.value}><input type="radio" name="vs-mode" checked={chosen === m.value} onChange={() => setMode(m.value)} />
                    <b>{m.title}</b><span>{m.about}</span></label>
                ))}
              </div>
              <p className="hint">ClipForge remembers your choice for next time.</p>
            </fieldset>
            {problem && <Banner tone="bad" title="Not started">{problem}</Banner>}
            <div className="vs-go">
              <button type="button" className="btn btn-primary btn-large" disabled={!ready || busy} onClick={submit}>
                <Icon name={chosen === "auto" ? "create" : "spark"} />
                {busy ? "Starting…" : chosen === "auto" ? "Build my video" : "Plan it with ClipForge AI"}
              </button>
              {!ready && <p className="small muted" aria-live="polite">{!ordered.length ? "Drop in at least one video first."
                : uploading ? "Wait until every file has uploaded." : "Add at least one video; your pictures and sounds go with it."}</p>}
            </div>
            <ModelLine model={model} />
          </section>
          <section className="panel" aria-labelledby="vs-more-h">
            <h2 id="vs-more-h">More choices</h2>
            <p className="small muted">Optional. What you don't say comes from your style, your example and your Brain.</p>
            <Disclosure summary="Style and example">
              <div className="stack-3">
                <StyleSelect value={style} onChange={setStyle} mode="full_video" />
                <ExampleSelect value={example} onChange={setExample} mode="full_video" />
                <label><input type="checkbox" checked={remembering} onChange={(e) => setRemember(e.target.checked)} /> Remember this video's look as a style</label>
                {remembering && <label className="field"><span>Style name</span><input value={styleName} maxLength={60} placeholder={`${name || "My video"} style`} onChange={(e) => setStyleName(e.target.value)} /></label>}
                <p className="small muted">Saves the plan's shape, feel and kind of video for next time. Your files and what to keep or cut stay in this video only.</p>
              </div>
            </Disclosure>
            <Disclosure summary={script ? "Your script (added)" : "Your script"}>
              <p className="small muted">If you read from a script, give it here: ClipForge finds every line in your footage and cuts one clip per line, in script order, using your cleanest take.</p>
              <ScriptDrop value={script} onChange={setScript} />
            </Disclosure>
            <Disclosure summary="Name this video">
              <label className="field"><span>Video name</span><input value={name} maxLength={120} placeholder="ClipForge AI can name it from your idea" onChange={(e) => setName(e.target.value)} /></label>
            </Disclosure>
          </section>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ planning: the conversation and the plan
function Planning({ id }: { id: string }) {
  const { appearance, set: setAppearance } = useAppearance();
  const { data: s, error, refresh, setData } = usePoll(() => studio.videoSetup(id), [id], 2000,
    (v) => !!v && v.planning && (v.thinking || v.listening));
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState("");
  const [editing, setEditing] = useState(false);
  const [building, setBuilding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [uploading, setUploading] = useState(0);
  const [formDirty, setFormDirty] = useState(false);
  const [unsent, setUnsent] = useState<SetupMode | "" | null>(null);  // Build pressed with words not sent yet
  const changed = useChanged(s?.plan);
  const log = useRef<HTMLDivElement>(null);
  const sayBox = useRef<HTMLTextAreaElement>(null);
  const handButton = useRef<HTMLButtonElement>(null);
  // the conversation and the plan are saved as you go; what is not saved yet is said before you leave
  const losing = [editing && formDirty && "your changes in the plan form", text.trim() && "the message you are writing",
    uploading > 0 && (uploading === 1 ? "a file still uploading" : `${uploading} files still uploading`)]
    .filter((x): x is string => !!x);
  const unsaved = losing.length ? `If you leave now, you lose ${losing.length > 1
    ? `${losing.slice(0, -1).join(", ")} and ${losing[losing.length - 1]}` : losing[0]}.` : "";
  useLeaveGuard(useMemo(() => (unsaved ? { what: losing.join(", "), say: unsaved } : null), [unsaved]));  // eslint-disable-line react-hooks/exhaustive-deps
  const last = s?.messages[s.messages.length - 1];

  useEffect(() => {
    if (s && !s.planning) redirect(`video/${s.id}`);  // built (here, or from the ClipForge AI panel), or never planned here
  }, [s?.planning, s?.id]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const el = log.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [s?.messages.length, last?.status]);

  if (!s) return error ? <div className="page"><Banner tone="bad" title="This video cannot be opened"
    actions={<a className="btn" href="#/projects">Projects</a>}>{error}</Banner></div> : <LoadingPage label="Loading your video" />;

  const run = async (call: () => Promise<VideoSetup>): Promise<boolean> => {
    setProblem("");
    try {
      const next = await call();
      setData(next);
      if (next.thinking || next.listening) refresh();
      return true;
    } catch (e) {
      setProblem(errorText(e));
      return false;
    }
  };
  const say = async (words: string, question = "") => {
    const t = words.trim();
    if (!t || sending) return;
    setSending(true);
    setProblem("");
    try {
      const out = await studio.sayToSetup(id, t, question);
      setData(out.setup);
      // words typed while it sent stay; the ones sent go
      if (!question) setText((now) => (now.startsWith(words) ? now.slice(words.length).replace(/^[\s,;]+/, "") : now.trim() === t ? "" : now));
      if (out.setup.thinking || out.setup.listening) refresh();
      if (question) window.requestAnimationFrame(() => sayBox.current?.focus());  // the answers you tapped are gone
    } catch (e) {
      setProblem(errorText(e));
    }
    setSending(false);
  };
  /** Build my video, Just do it: words typed but not sent are asked about first (the page leaves when it builds). */
  const tryBuild = (mode: SetupMode | "" = "") => {
    if (text.trim()) setUnsent(mode);
    else void build(mode);
  };
  const build = async (mode: SetupMode | "" = "") => {
    setBuilding(true);
    setProblem("");
    try {
      const out = await studio.buildSetup(id, mode);
      redirect(out.href);  // Back from the editor does not land on a page that sends you on again
    } catch (e) {
      setProblem(errorText(e));
      setBuilding(false);
    }
  };
  const savePlan = async (changes: Partial<PlanFields>) => {
    if (Object.keys(changes).length) {
      setSaving(true);
      const ok = await run(() => studio.changeSetup(id, { plan: changes }));
      setSaving(false);
      if (!ok) return;  // the form stays open with what you typed; the problem shows above
      toast("Plan saved");
    }
    closeForm();
  };
  const closeForm = () => {
    setEditing(false);
    setFormDirty(false);
    window.requestAnimationFrame(() => handButton.current?.focus());
  };
  const stop = async () => {
    setStopping(true);
    await run(() => studio.stopSetup(id));
    setStopping(false);
  };
  const ids = s.files.map((f) => f.id);
  const reorder = (next: string[]) => run(() => studio.changeSetup(id, { asset_ids: next }));
  const move = (fid: string, by: number) => {
    const i = ids.indexOf(fid);
    const j = Math.max(0, Math.min(ids.length - 1, i + by));
    const next = [...ids];
    next.splice(i, 1);
    next.splice(j, 0, fid);
    void reorder(next);
  };
  const keyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void say(text);
    }
  };
  const open = last && last.role === "ai" && last.status === "done" ? s.open : [];
  const waitFor = uploading > 0 ? "Build my video waits until your files have uploaded."
    : editing && formDirty ? "Save or cancel your changes to the plan first." : "";

  return (
    <div className="page">
      <PageHead kind="Make" title={s.name} crumbs={[{ label: "Projects", href: "#/projects" }, { label: s.name }]}
        sub="Planning with ClipForge AI. The conversation and the plan are saved as you go: leave any time and come back from Projects." />
      {problem && <Banner tone="bad" title="That didn't work">{problem}</Banner>}
      <div className="studio-grid">
        <section className="panel" aria-labelledby="vs-talk-h">
          <div className="panel-head">
            <h2 id="vs-talk-h">Talk it through</h2>
            <Toggle on={s.mode === "ask"} label="Ask me questions" onChange={(on) => {
              const mode: SetupMode = on ? "ask" : "auto";
              void run(() => studio.changeSetup(id, { mode })).then((ok) => { if (ok && mode !== appearance.video_setup_mode) setAppearance({ video_setup_mode: mode }); });
            }} />
          </div>
          <div className="vs-talk" ref={log} role="log" aria-live="polite" aria-label="Conversation with ClipForge AI">
            {s.messages.length === 0 && <p className="cfai-empty">Tell ClipForge AI your idea below.</p>}
            {s.messages.map((m) => (
              <Message key={m.id} m={m} open={m === last ? open : []} busy={sending || building} stopping={stopping}
                waitFor={waitFor} onAnswer={(q, choice) => void say(choice, q.id)} onJustDoIt={() => tryBuild("auto")}
                onStop={() => void stop()} />
            ))}
          </div>
          <form className="vs-say" onSubmit={(e) => { e.preventDefault(); void say(text); }}>
            <label className="sr-only" htmlFor="vs-say-box">Tell ClipForge AI</label>
            <textarea id="vs-say-box" ref={sayBox} value={text} maxLength={4000} onChange={(e) => setText(e.target.value)} onKeyDown={keyDown}
              placeholder={s.messages.some((m) => m.role === "owner") ? "Change something: “make it 8 minutes”, “no music”, “open with the jump”…"
                : "Tell ClipForge AI your idea: what happens, who it's for, how long, the feel…"} />
            <div className="vs-say-row">
              <span className="hint">Enter sends. Shift+Enter starts a new line.</span>
              <button type="submit" className="btn" disabled={!text.trim() || sending || s.thinking}>
                <Icon name="spark" />{s.thinking ? "ClipForge AI is answering…" : sending ? "Sending…" : "Send"}</button>
            </div>
          </form>
          <ModelLine model={s.model} />
        </section>
        <div className="stack-5">
          <section className="panel" aria-labelledby="vs-plan-h">
            <div className="panel-head"><h2 id="vs-plan-h">The plan</h2>
              {s.planned && <span className="small muted">{s.source === "ai" ? "Written by ClipForge AI" : "Read by the built-in rules"}</span>}</div>
            {editing
              ? <PlanForm plan={s.plan} files={s.files} busy={saving} saveLabel="Save the plan" onSave={savePlan} onCancel={closeForm}
                onDirty={setFormDirty} />
              : <PlanSheet name={s.name} plan={s.plan} files={s.files} changed={changed} />}
            {!editing && <div className="vs-plan-actions">
              <button type="button" className="btn btn-primary" disabled={building || s.thinking || uploading > 0} onClick={() => tryBuild()}>
                <Icon name="create" />{building ? "Starting…" : "Build my video"}</button>
              <button type="button" ref={handButton} className="btn" onClick={() => setEditing(true)}><Icon name="edit" />Change it by hand</button>
            </div>}
            {s.thinking && !editing && <p className="small muted">Build my video waits until ClipForge AI has answered.</p>}
            {!s.thinking && !editing && uploading > 0 && <p className="small muted">Build my video waits until your files have uploaded.</p>}
            {s.locked.length > 0 && !editing && <p className="small muted">What you changed by hand stays as you set it until you talk about it again.</p>}
          </section>
          <FilesPanel s={s} onMove={move} onRemove={(fid) => void reorder(ids.filter((x) => x !== fid))}
            onAdded={() => refresh()} onProblem={setProblem} onUploading={setUploading} />
          <MoreChoices s={s} run={run} />
        </div>
      </div>
      {unsent !== null && (
        <Dialog title="Send your message first?" onClose={() => setUnsent(null)} actions={<>
          <button type="button" className="btn btn-quiet" onClick={() => setUnsent(null)}>Stay</button>
          <button type="button" className="btn" onClick={() => { const mode = unsent; setUnsent(null); void build(mode); }}>Build without it</button>
          <button type="button" className="btn btn-primary" data-autofocus onClick={() => { setUnsent(null); void say(text); }}>Send it first</button>
        </>}>
          <p className="muted">You wrote a message but did not send it. Send it so ClipForge AI plans with it, then build; or build with the plan as it is.</p>
        </Dialog>
      )}
    </div>
  );
}

/** One message of the conversation. The newest answer carries the open questions with quick answers. */
function Message({ m, open, busy, stopping, waitFor, onAnswer, onJustDoIt, onStop }: {
  m: SetupMessage; open: SetupQuestion[]; busy: boolean; stopping: boolean; waitFor: string;
  onAnswer: (q: SetupQuestion, choice: string) => void; onJustDoIt: () => void; onStop: () => void;
}) {
  if (m.role === "owner") return <div className="cfai-msg owner"><p className="vs-text">{m.text}</p></div>;
  if (m.status === "thinking") {
    return (
      <div className="cfai-msg ai" aria-busy="true">
        <div className="vs-thinking"><span className="inline-spinner" aria-hidden="true" />Thinking about your video…</div>
        <div><button type="button" className="btn btn-small" disabled={stopping} onClick={onStop}><Icon name="stop" />{stopping ? "Stopping…" : "Stop"}</button></div>
      </div>
    );
  }
  const d = m.data || {};
  const helpers = d.helpers || [];
  const asked = open.length ? [] : d.questions || [];
  return (
    <div className={`cfai-msg ai${m.status === "failed" ? " failed" : ""}`}>
      <Who m={m} />
      <p className="vs-text">{d.tool === "plan" && d.say ? d.say : m.text}</p>
      {asked.length > 0 && <ul className="small muted vs-asked">{asked.map((q) => <li key={q.id}>{q.q}</li>)}</ul>}
      {open.length > 0 && (
        <div className="vs-asks">
          {open.map((q) => (
            <div key={q.id} className="vs-ask">
              <p>{q.q}</p>
              {q.choices.length > 0 && <div className="chip-row">
                {q.choices.map((c) => <button key={c} type="button" className="chip" disabled={busy} onClick={() => onAnswer(q, c)}>{c}</button>)}
              </div>}
            </div>
          ))}
          <div className="chip-row">
            <button type="button" className="chip vs-just" disabled={busy || !!waitFor} onClick={onJustDoIt}><Icon name="spark" size={14} /> Just do it</button>
          </div>
          <p className="hint">{waitFor || "Tap an answer, write your own below, or press Just do it to build with the plan as it is."}</p>
        </div>
      )}
      {helpers.length > 0 && (
        <Disclosure summary={`Notes from your helper${helpers.length === 1 ? "" : "s"} (${helpers.length})`}>
          <ul className="vs-helpers">
            {helpers.map((h, i) => <li key={i} className={h.ok ? "" : "failed"}><b>{h.agent.name}</b><span>{h.text}</span></li>)}
          </ul>
        </Disclosure>
      )}
    </div>
  );
}

/** Who answered: the model (and whether the words left this computer) or the built-in rules. */
function Who({ m }: { m: SetupMessage }) {
  const d = m.data || {};
  if (d.tool !== "plan") return null;
  const where = d.sent ? d.sent.split(":")[0] : "";
  return (
    <span className="vs-who">
      <Icon name={d.source === "ai" ? "spark" : "cpu"} />
      <span>{d.source === "ai" ? `ClipForge AI${d.provider ? ` with ${d.provider}` : ""}` : "ClipForge AI's built-in rules"}</span>
      {d.source === "ai" && where && <span title={d.sent}>{where}</span>}
      {!!d.used?.length && <span title={d.used.map((u) => u.text).join("\n")}>Used {d.used.length} of your memories</span>}
    </span>
  );
}

const KIND: Record<SetupFile["kind"], string> = { video: "Video", image: "Picture", audio: "Sound" };

/** What ClipForge AI heard in a video so far. */
function Heard({ f }: { f: SetupFile }) {
  if (f.kind !== "video" || !f.state) return null;
  if (f.state === "listening") return <span className="vs-heard"><span className="inline-spinner" aria-hidden="true" />Listening…</span>;
  if (f.state === "waiting") return <span className="vs-heard"><Icon name="clock" />Waiting its turn to be listened to</span>;
  if (f.state === "silent") return <span className="vs-heard"><Icon name="info" />No speech heard</span>;
  return <span className="vs-heard good"><Icon name="check" />Heard {f.words.toLocaleString()} word{f.words === 1 ? "" : "s"}</span>;
}

/** The draft's files, with what was heard in each; reorder, take out or add more. */
function FilesPanel({ s, onMove, onRemove, onAdded, onProblem, onUploading }: {
  s: VideoSetup; onMove: (id: string, by: number) => void; onRemove: (id: string) => void; onAdded: () => void;
  onProblem: (text: string) => void; onUploading: (count: number) => void;
}) {
  const [uploads, setUploads] = useState<Picked[]>([]);
  const [local, setLocal] = useState<"unknown" | "yes" | "no">("unknown");
  const [browsing, setBrowsing] = useState(false);
  const added = useRef(new Set<string>());
  const sent = useRef(new Set<string>());  // uploads sent with their file
  useEffect(() => {
    let alive = true;
    studio.localBrowse("").then(() => alive && setLocal("yes")).catch(() => alive && setLocal("no"));
    return () => { alive = false; };
  }, []);
  const inVideo = (id: string) => s.files.some((f) => f.id === id);
  const add = (assets: Asset[], again = false) => {
    // picked on purpose: also one taken out before (one still in the video stays known, so taking it out later holds)
    if (again) assets.filter((a) => !inVideo(a.id)).forEach((a) => added.current.delete(a.id));
    const fresh = assets.filter((a) => !added.current.has(a.id) && !inVideo(a.id));
    // each upload is sent once with its file, also one of a file the video has already, so it is the video's own
    const mine = assets.filter((a) => a.upload_id && !sent.current.has(a.upload_id) && (fresh.includes(a) || inVideo(a.id)));
    if (!fresh.length && !mine.length) return;
    const ups = uploadIds(mine);
    fresh.forEach((a) => added.current.add(a.id));
    ups.forEach((u) => sent.current.add(u));
    studio.addVideoMedia(s.id, [...new Set([...fresh, ...mine].map((a) => a.id))], ups).then(onAdded).catch((e) => {
      fresh.forEach((a) => added.current.delete(a.id));
      ups.forEach((u) => sent.current.delete(u));
      onProblem(errorText(e));
    });
  };
  // files join the video in the order you dropped them, each as soon as it and the ones before it have uploaded
  const have = s.files.map((f) => f.id).join(" ");
  useEffect(() => {
    const ready: Asset[] = [];
    for (const r of uploads) {
      if (r.asset) ready.push(r.asset);
      else if (!r.error) break;
    }
    add(ready);
  }, [uploads, have]);  // eslint-disable-line react-hooks/exhaustive-deps
  const sending = uploads.filter((r) => !r.asset && !r.error);
  useEffect(() => onUploading(sending.length), [sending.length]);  // eslint-disable-line react-hooks/exhaustive-deps
  const videos = s.files.filter((f) => f.kind === "video").length;
  return (
    <section className="panel" aria-labelledby="vs-files-h">
      <h2 id="vs-files-h">Your files ({s.files.length})</h2>
      {s.listening && <p className="small muted">ClipForge AI is listening to your videos, so it can plan with what is said in them.</p>}
      <ol className="vs-files" aria-label="Your files in order">
        {s.files.map((f, i) => (
          <li key={f.id} className="file-row">
            {f.thumbnail ? <img className="thumb-mini" src={`/api/assets/${f.id}/thumbnail`} alt="" /> : <span className="thumb-mini" aria-hidden="true" />}
            <div className="break">
              <b>{f.filename}</b>
              <span className="muted">{KIND[f.kind]}{f.kind !== "image" && f.duration ? `, ${fmtTime(f.duration)}` : ""}</span>
              <Heard f={f} />
            </div>
            <div className="row-actions">
              <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${f.filename} up`} disabled={i === 0} onClick={() => onMove(f.id, -1)}><Icon name="chev" className="vs-up" /></button>
              <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${f.filename} down`} disabled={i === s.files.length - 1} onClick={() => onMove(f.id, 1)}><Icon name="chev" className="vs-down" /></button>
              <button type="button" className="btn btn-small btn-icon" aria-label={`Take ${f.filename} out of this video`}
                disabled={s.files.length === 1 || (f.kind === "video" && videos === 1)} onClick={() => onRemove(f.id)}><Icon name="x" /></button>
            </div>
          </li>
        ))}
        {sending.map((r) => <li key={r.key}><UploadRow row={r} /></li>)}
      </ol>
      <p className="small muted">Videos and pictures play in this order. Moving one keeps your order over the plan's.</p>
      <Disclosure summary="Add files">
        <div className="stack-3">
          <FileDrop accept={ACCEPT} multiple label="Drop more videos, pictures and sounds" onAssets={setUploads}
            onPicked={(keys) => add(uploads.filter((r) => keys.includes(r.key) && r.asset).map((r) => r.asset!), true)} />
          {local === "yes" && !browsing && <button type="button" className="btn local-pick" onClick={() => setBrowsing(true)}><Icon name="folder" />Add from this computer</button>}
          {browsing && <LocalFiles onLinked={(assets) => add(assets, true)} onClose={() => setBrowsing(false)} />}
        </div>
      </Disclosure>
    </section>
  );
}

/** Name, style, example, remembering the look and the script, changed on the draft as you go. */
function MoreChoices({ s, run }: { s: VideoSetup; run: (call: () => Promise<VideoSetup>) => Promise<boolean> }) {
  const [name, setName] = useState(s.name);
  const [styleName, setStyleName] = useState(s.remember.name || "");
  useEffect(() => setName(s.name), [s.name]);
  const change = (changes: Record<string, unknown>) => run(() => studio.changeSetup(s.id, changes));
  const remembering = !!s.remember.enabled;
  return (
    <section className="panel" aria-labelledby="vs-more-h">
      <h2 id="vs-more-h">More choices</h2>
      <Disclosure summary="Name">
        <form className="row wrap" onSubmit={(e) => { e.preventDefault(); if (name.trim() && name.trim() !== s.name) void change({ name: name.trim() }); }}>
          <label className="field grow"><span>Video name</span><input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></label>
          <button type="submit" className="btn" disabled={!name.trim() || name.trim() === s.name}>Rename</button>
        </form>
      </Disclosure>
      <Disclosure summary="Style and example">
        <div className="stack-3">
          <StyleSelect value={s.style_id} onChange={(v) => void change({ style_id: v })} mode="full_video" />
          <ExampleSelect value={s.reference_id} onChange={(v) => void change({ reference_id: v })} mode="full_video" />
          <label><input type="checkbox" checked={remembering} onChange={(e) => void change({ remember: { enabled: e.target.checked, name: styleName.trim() } })} /> Remember this video's look as a style</label>
          {remembering && <label className="field"><span>Style name</span><input value={styleName} maxLength={60} placeholder={`${s.name} style`}
            onChange={(e) => setStyleName(e.target.value)} onBlur={() => { if (styleName.trim() !== (s.remember.name || "")) void change({ remember: { enabled: true, name: styleName.trim() } }); }} /></label>}
        </div>
      </Disclosure>
      <Disclosure summary={s.script ? "Your script (added)" : "Your script"}>
        <p className="small muted">If you read from a script, give it here: ClipForge finds every line in your footage and cuts one clip per line, in script order.</p>
        <ScriptDrop value={s.script} onChange={(sc) => void change({ script: sc })} />
      </Disclosure>
    </section>
  );
}
