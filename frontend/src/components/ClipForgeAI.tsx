import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "../api";
import { Chat, chatApi, ChatMessage, UsedKnowHow, UsedMemory } from "../brain";
import { ChangeRequest, Video } from "../studio";
import { Icon, Pill, toast } from "./ui";

const TONE: Record<ChangeRequest["status"], "good" | "warn" | "bad" | "neutral"> = {
  thinking: "neutral", ready: "good", question: "warn", unsupported: "neutral", invalid: "bad", failed: "bad",
  canceled: "neutral", applied: "good", stale: "warn",
};
const WORD: Record<ChangeRequest["status"], string> = {
  thinking: "Working on it", ready: "Ready to check", question: "Question", unsupported: "Not done", invalid: "Refused",
  failed: "Failed", canceled: "Discarded", applied: "Applied", stale: "Out of date",
};

/** Plain text from ClipForge AI: paragraphs, and lines that start with "- " as a list. */
function Lines({ text }: { text: string }) {
  const blocks: { list: boolean; lines: string[] }[] = [];
  for (const line of text.split("\n")) {
    const item = line.startsWith("- ");
    const last = blocks[blocks.length - 1];
    if (last && last.list === item && item) last.lines.push(line.slice(2));
    else blocks.push({ list: item, lines: [item ? line.slice(2) : line] });
  }
  return <>{blocks.map((b, i) => b.list
    ? <ul key={i} className="small change-list">{b.lines.map((l, j) => <li key={j}>{l}</li>)}</ul>
    : <Fragment key={i}>{b.lines.filter((l) => l.trim()).map((l, j) => <p key={j}>{l}</p>)}</Fragment>)}</>;
}

const Used = ({ used }: { used?: UsedMemory[] }) => used && used.length
  ? <p className="small muted">From your brain: {used.map((m) => `[${m.kind}] ${m.text}`).join("; ")}</p> : null;
const KnowHow = ({ knowhow }: { knowhow?: UsedKnowHow[] }) => knowhow && knowhow.length
  ? <p className="small muted">From its know-how: {knowhow.map((k) => k.title.toLowerCase()).join("; ")} (Brain → Memory)</p> : null;

/**
 * ClipForge AI's chat. On a video: say what to change, and it proposes a checked change you apply as a new version
 * (Undo takes it back) or discard. Anywhere: teach it ("remember: …", "always …", "never …"), ask what it knows,
 * ask why it did something, or ask a question (answered by the model from Settings → ClipForge AI, with the memories
 * it recalled; text only, never the video or the sound).
 */
export function ClipForgeAI({ projectId = "", v, busy = false, onApplied, tall = false }: {
  projectId?: string; v?: Video; busy?: boolean; onApplied?: () => void; tall?: boolean;
}) {
  const [chat, setChat] = useState<Chat | null>(null);
  const [msgs, setMsgs] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [working, setWorking] = useState(false);
  const [problem, setProblem] = useState("");
  const log = useRef<HTMLDivElement>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let gone = false;
    chatApi.open(projectId).then((c) => { if (!gone) { setChat(c); setMsgs(c.messages); setProblem(""); } })
      .catch((e) => { if (!gone) setProblem(errorText(e)); });
    return () => { gone = true; };
  }, [projectId]);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const thinking = msgs.some((m) => m.status === "thinking");
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!chat || !thinking) return;
    timer.current = window.setTimeout(async () => {
      try { setMsgs(await chatApi.messages(chat.id)); } catch (e) { toast(errorText(e), true); }
    }, 800);
  }, [chat, thinking, msgs]);
  useEffect(() => {
    const el = log.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs.length, thinking]);

  const replace = useCallback((m: ChatMessage) => setMsgs((all) => all.map((x) => (x.id === m.id ? m : x))), []);
  const send = async (words: string) => {
    if (!chat || !words.trim()) return;
    setWorking(true);
    try {
      const r = await chatApi.say(chat.id, words.trim(), v?.plan_revision);
      setMsgs((all) => [...all, r.owner, r.ai]);
      setText("");
    } catch (e) { toast(errorText(e), true); }
    setWorking(false);
  };
  const act = async (m: ChatMessage, what: "apply" | "discard") => {
    if (!chat) return;
    setWorking(true);
    try {
      const r = await chatApi[what](chat.id, m.id);
      replace(r);
      if (what === "apply") {
        toast(`Applied as version ${r.data.request?.applied_revision}. Undo takes it back.`);
        onApplied?.();
      }
    } catch (e) {
      toast(errorText(e), true);
      try { setMsgs(await chatApi.messages(chat.id)); } catch { /* the toast already says why */ }
    }
    setWorking(false);
  };
  const clear = async () => {
    if (!chat) return;
    try { await chatApi.clear(chat.id); setMsgs([]); } catch (e) { toast(errorText(e), true); }
  };

  const examples = v ? ["Move the summit part before lunch", "Remember: my intro is 3 seconds", "What do you know?"]
    : ["Remember: my videos are about hiking", "Never zoom in on faces", "How loud should my video be?"];
  return (
    <section className={`cfai${tall ? " tall" : ""}`} aria-labelledby={`cfai-${projectId || "all"}`}>
      <div className="cfai-head">
        <h3 id={`cfai-${projectId || "all"}`} className="row"><Icon name="spark" />ClipForge AI</h3>
        {msgs.length > 0 && <button type="button" className="btn btn-small" onClick={() => void clear()}>Clear this chat</button>}
      </div>
      <p className="small muted">{v ? "Say what to change and it proposes a checked change; nothing changes until you press Apply. "
        : "Ask it anything about your videos and your channel. "}
        Teach it with “remember: …”, “always …” or “never …”; ask “what do you know?” or “why?”; ask how to edit
        (hooks, pacing, captions, sound, music, colour, export) and it answers from its built-in know-how. Say “help” for more.
        {" "}What it needs a model for is sent as text only, never the video or the sound.</p>
      {problem && <p className="error-text"><Icon name="alert" />{problem}</p>}
      <div ref={log} className="cfai-log" aria-live="polite" aria-label="Conversation">
        {msgs.length === 0 && !problem && <>
          <div className="cfai-chips" aria-label="Examples">
            {examples.map((x) => <button key={x} type="button" className="btn btn-small ask-choice" disabled={!chat || working} onClick={() => void send(x)}>{x}</button>)}
          </div>
          <p className="cfai-empty">Your conversation with ClipForge AI shows here.</p>
        </>}
        {msgs.map((m) => m.role === "owner"
          ? <div key={m.id} className="cfai-msg owner"><p>{m.text}</p></div>
          : <Answer key={m.id} m={m} busy={busy || working} onAct={act} onSend={send} />)}
      </div>
      <form className="cfai-row" onSubmit={(e) => { e.preventDefault(); void send(text); }}>
        <label className="field grow"><span>{v ? "Tell ClipForge AI what to change, or ask it something" : "Talk to ClipForge AI"}</span>
          <input value={text} maxLength={500} onChange={(e) => setText(e.target.value)} disabled={!chat}
            placeholder={v ? "For example: move the summit part before lunch" : "For example: remember that my intro is 3 seconds"} /></label>
        <button type="submit" className="btn btn-primary" disabled={!chat || busy || working || !text.trim()}>
          {working ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="spark" />}Send</button>
      </form>
    </section>
  );
}

function Answer({ m, busy, onAct, onSend }: {
  m: ChatMessage; busy: boolean; onAct: (m: ChatMessage, what: "apply" | "discard") => Promise<void>; onSend: (words: string) => Promise<void>;
}) {
  const d = m.data || {};
  const r = d.tool === "change" ? d.request : undefined;
  const p = r?.proposal;
  return (
    <div className={`cfai-msg ai${m.status === "failed" ? " failed" : ""}`}>
      {r && <div className="row wrap">
        <Pill tone={TONE[r.status]}>{WORD[r.status]}</Pill>
        <span className="small muted">{r.source !== "ai" ? "Understood without a model" : r.status === "thinking" ? `Asking ${r.provider}` : `Answered by ${r.provider}`}</span>
      </div>}
      {m.status === "thinking" && <p className="row small"><span className="inline-spinner" aria-hidden="true" />{m.text}</p>}
      {m.status !== "thinking" && <Lines text={m.text} />}
      {r?.status === "ready" && <div className="row wrap">
        <button type="button" className="btn btn-primary btn-small" disabled={busy} onClick={() => void onAct(m, "apply")}><Icon name="check" />Apply as a new version</button>
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => void onAct(m, "discard")}>Discard</button>
      </div>}
      {r?.status === "thinking" && <div><button type="button" className="btn btn-small" disabled={busy} onClick={() => void onAct(m, "discard")}><Icon name="stop" />Cancel</button></div>}
      {r?.status === "question" && (p?.choices || []).length > 0 && <div className="row wrap" role="group" aria-label="Choose one">
        {(p?.choices || []).map((c) => <button key={c.request} type="button" className="btn btn-small ask-choice" disabled={busy} onClick={() => void onSend(c.request)}>{c.label}</button>)}
      </div>}
      {d.tool === "forget" && (d.candidates || []).length > 0 && <div className="row wrap" role="group" aria-label="Forget one">
        {(d.candidates || []).map((c) => <button key={c.id} type="button" className="btn btn-small ask-choice" disabled={busy} onClick={() => void onSend(`forget ${c.text}`)}><Icon name="trash" />Forget “{c.text}”</button>)}
      </div>}
      {(d.tool === "change" || d.tool === "answer" || d.tool === "explain") && <Used used={d.used} />}
      {(d.tool === "change" || d.tool === "answer" || d.tool === "explain") && <KnowHow knowhow={d.knowhow} />}
      {(r?.sent || (d.tool === "answer" && d.sent)) && m.status !== "failed" && <p className="small muted">{r?.sent || d.sent}</p>}
    </div>
  );
}
