import {
  Fragment, KeyboardEvent as ReactKeyboardEvent, memo, MouseEvent as ReactMouseEvent, useCallback, useEffect, useId,
  useLayoutEffect, useMemo, useRef, useState,
} from "react";
import { api, BuiltinTask, errorText } from "../api";
import {
  Chat, ChatAction, ChatActionState, ChatAgent, ChatAi, chatApi, ChatAsk, ChatData, ChatMessage, ChatStep, HelperWork,
  MAX_CHAT_TEXT, Memory, memoryApi,
} from "../brain";
import { useAppearance } from "../prefs";
import { navigate } from "../router";
import { ChangeRequest, Video } from "../studio";
import { BuiltinProgress } from "./AiHelperSettings";
import { ConfirmDialog, Icon, IconName, Pill, toast } from "./ui";

const TONE: Record<ChangeRequest["status"], "good" | "warn" | "bad" | "neutral"> = {
  thinking: "neutral", ready: "good", question: "warn", unsupported: "neutral", invalid: "bad", failed: "bad",
  canceled: "neutral", applied: "good", stale: "warn",
};
const WORD: Record<ChangeRequest["status"], string> = {
  thinking: "Working on it", ready: "Ready to check", question: "Question", unsupported: "Not done", invalid: "Refused",
  failed: "Failed", canceled: "Discarded", applied: "Applied", stale: "Out of date",
};
const ACTION_STATE: Record<Exclude<ChatActionState, "waiting">, { tone: string; icon: IconName; word: string }> = {
  done: { tone: "good", icon: "check", word: "Done" },
  failed: { tone: "bad", icon: "alert", word: "It did not work" },
  skipped: { tone: "neutral", icon: "x", word: "You said no, so nothing changed" },
  blocked: { tone: "warn", icon: "alert", word: "This cannot be done right now" },
};
const POLL_WRITING_MS = 350;    // an answer being written: show it growing
const POLL_REQUEST_MS = 1200;   // a proposed change being worked out
const POLL_RETRY_MS = 2500;     // the app did not answer: try again a little later
const POLL_HIDDEN_MS = 3000;    // nobody is looking at the page: less often (it catches up when you come back)
const gbText = (bytes: number) => `${(bytes / 1e9).toFixed(1)} GB`;
/** A press by keyboard or mouse, not by a finger: moving the focus into the message box then opens no phone keyboard. */
const notTouch = (e: ReactMouseEvent) => e.detail === 0 || (e.nativeEvent as PointerEvent).pointerType === "mouse";
/** Nothing has the focus: the button that had it went away, or was switched off while its work ran. */
const focusLost = () => !document.activeElement || document.activeElement === document.body;
/** A result line as a sentence: a full stop at the end unless it already ends one ("Renamed to “X”" → "…”."). */
const sentence = (s: string) => {
  const t = s.trim();
  return !t || /[.!?…]["”’)]*$/.test(t) ? t : `${t}.`;
};

/** Bold (**…**) and code (`…`) inside a line, the two marks models use most. Everything else stays plain text. */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g);
  return <>{parts.map((p, i) => p.length > 4 && p.startsWith("**") && p.endsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong>
    : p.length > 2 && p.startsWith("`") && p.endsWith("`") ? <code key={i}>{p.slice(1, -1)}</code>
      : <Fragment key={i}>{p}</Fragment>)}</>;
}

type Block = { kind: "p" | "ul" | "ol" | "h"; lines: string[]; start?: number };

/** Words from ClipForge AI or a helper: paragraphs, "- " and "1. " lists, and short headings ("## …"). */
function Lines({ text }: { text: string }) {
  const blocks: Block[] = [];
  const add = (kind: Block["kind"], line: string, start?: number) => {
    const last = blocks[blocks.length - 1];
    if (last && last.kind === kind && (kind === "ul" || kind === "ol")) last.lines.push(line);
    else blocks.push({ kind, lines: [line], start });
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    let m: RegExpExecArray | null;
    if (!line.trim()) blocks.push({ kind: "p", lines: [] });  // an empty line ends a list
    else if ((m = /^\s*[-*•]\s+(.*)$/.exec(line))) add("ul", m[1]);
    else if ((m = /^\s*(\d{1,3})[.)]\s+(.*)$/.exec(line))) add("ol", m[2], Number(m[1]));
    else if ((m = /^\s*#{1,4}\s+(.*)$/.exec(line))) add("h", m[1]);
    else add("p", line);
  }
  return <>{blocks.map((b, i) => b.kind === "ul"
    ? <ul key={i} className="cfai-list">{b.lines.map((l, j) => <li key={j}><Inline text={l} /></li>)}</ul>
    : b.kind === "ol" ? <ol key={i} className="cfai-list" start={b.start}>{b.lines.map((l, j) => <li key={j}><Inline text={l} /></li>)}</ol>
      : b.lines.length ? <p key={i} className={b.kind === "h" ? "cfai-h" : undefined}><Inline text={b.lines[0]} /></p> : null)}</>;
}

/** "@Script writer write me a hook" → the helper it names (the longest name that fits), or null. */
function mentionOf(text: string, agents: ChatAgent[]): ChatAgent | null {
  if (!text.startsWith("@")) return null;
  const low = text.slice(1).toLowerCase();
  const hits = agents.filter((a) => low.startsWith(a.name.toLowerCase()) && !/[\p{L}\p{N}]/u.test(low.charAt(a.name.length)));
  return hits.sort((x, y) => y.name.length - x.name.length)[0] || null;
}

/** Messages from the server after `after`, put in place of the ones this page had; newer ones it already shows stay
 * (you sent them while this answer was on its way). None at all: the chat was cleared somewhere else, so they go. */
function merge(all: ChatMessage[], after: string, fresh: ChatMessage[]): ChatMessage[] {
  const at = after ? all.findIndex((m) => m.id === after) : -1;
  if (after && at < 0) return all;
  const head = all.slice(0, at + 1);
  const seen = new Set([...head, ...fresh].map((m) => m.id));
  const newest = fresh.length ? fresh[fresh.length - 1].created_at : Infinity;
  const extra = all.slice(at + 1).filter((m) => !seen.has(m.id) && m.created_at >= newest);
  return [...head, ...fresh.filter((m) => !head.some((h) => h.id === m.id)), ...extra];
}

/** Starts the built-in model's download (or switches to a level already downloaded) and follows it every 1.5 s. */
function useBuiltinInstall(initial: BuiltinTask | undefined, onDone: () => void) {
  const [task, setTask] = useState<BuiltinTask>(initial || {});
  const [busy, setBusy] = useState(false);
  const done = useRef(onDone);
  done.current = onDone;
  const finished = useRef(false);
  const running = task.state === "running";
  useEffect(() => {
    if (!running) return;
    finished.current = false;
    const t = window.setInterval(() => {
      void api.builtinAi().then((b) => {
        setTask(b.task || {});
        if (b.task?.state === "done" && !finished.current) {
          finished.current = true;
          done.current();
        }
      }).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(t);
  }, [running]);
  const start = async (level: string) => {
    setBusy(true);
    try {
      setTask(await api.builtinInstall(level));
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
  };
  const cancel = async () => {
    try {
      setTask(await api.builtinCancel());
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  return { task, start, cancel, busy };
}

/**
 * ClipForge AI's chat: on a video's page (that video's chat) and in Brain → Talk (the general chat). With a model it
 * is a real conversation: it answers with the chat so far, your projects and what you taught it, uses its tools
 * (each shown as a step), hands jobs to your helper agents, and anything that changes or deletes something waits for
 * your OK. "@Name …" talks to one helper directly. On a video it also proposes checked changes you apply as a new
 * version (Undo takes it back) or discard. Without a model it offers to set up the built-in one and still remembers,
 * forgets, lists and explains.
 */
export function ClipForgeAI({ projectId = "", v, busy = false, onApplied, tall = false, side = false }: {
  projectId?: string; v?: Video; busy?: boolean; onApplied?: () => void; tall?: boolean;
  /** show the switched-on helpers in a side panel (Brain → Talk) */
  side?: boolean;
}) {
  const uid = useId();
  const [chat, setChat] = useState<Chat | null>(null);
  const [msgs, setMsgs] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [acting, setActing] = useState(false);
  const [stopping, setStopping] = useState("");
  const [problem, setProblem] = useState("");
  const [chatGone, setChatGone] = useState(false);  // only this stops reading an answer: never a passing failure
  const [lost, setLost] = useState("");
  const [retry, setRetry] = useState(0);
  const [clearing, setClearing] = useState(false);
  const [focused, setFocused] = useState(false);
  const [caret, setCaret] = useState(0);
  const [hush, setHush] = useState<string | null>(null);
  const [pick, setPick] = useState(0);
  const [heard, setHeard] = useState(false);
  const log = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const stick = useRef(true);
  const nextCaret = useRef<number | null>(null);
  const opened = useRef(0);
  // what is on its way right now, known at once (a second press in the same moment must not send or act twice)
  const sendingNow = useRef(false);
  const actingNow = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  const { forgetPin } = useAppearance();

  const open = useCallback(async () => {
    const n = ++opened.current;
    try {
      const c = await chatApi.open(projectId);
      if (n !== opened.current) return;
      setChat(c);
      setMsgs(c.messages);
      setProblem("");
      setChatGone(false);
      setLost("");
    } catch (e) {
      if (n === opened.current) setProblem(errorText(e));
    }
  }, [projectId]);
  useEffect(() => { void open(); }, [open]);
  // The conversation reads new messages out to a screen reader, but not the whole chat when it first opens.
  useEffect(() => {
    if (!chat || heard) return;
    const t = window.setTimeout(() => setHeard(true), 400);
    return () => window.clearTimeout(t);
  }, [chat, heard]);

  const ai = chat?.ai;
  const ready = !!ai?.ready;
  const agents = useMemo(() => chat?.agents || [], [chat]);
  const helpers = useMemo(() => (ready ? agents : []), [ready, agents]);  // they think with the same model: none, no @
  const writing = msgs.find((m) => m.status === "thinking");
  const working = msgs.some((m) => m.data?.request?.status === "thinking");
  const placeholder = writing ? "ClipForge AI is answering… press Stop to end it early"
    : !chat || ready ? (projectId ? "Ask about this video, or say what to change" : "Message ClipForge AI")
      : "Teach it something, or ask an editing question";

  // While an answer is written (or a proposed change worked out), read the messages from the first one still going.
  // One read at a time; it stops when nothing is going any more, when this chat closes, or when the chat is gone
  // (not when another request failed for a moment: the answer keeps coming in under that message).
  const polling = !!chat && !chatGone && (!!writing || working);
  useEffect(() => {
    if (!chat || !polling) return;
    const first = msgs.findIndex((m) => m.status === "thinking" || m.data?.request?.status === "thinking");
    const after = first > 0 ? msgs[first - 1].id : "";
    let gone = false;
    const t = window.setTimeout(async () => {
      try {
        const fresh = await chatApi.messages(chat.id, after);
        if (gone) return;
        setLost("");
        setMsgs((all) => merge(all, after, fresh));
      } catch (e) {
        if (gone) return;
        const why = errorText(e);
        if (/not found/i.test(why)) {  // the chat itself is gone: asking again would never help
          setLost("");
          setChatGone(true);
          setProblem("This chat is gone. When its video is deleted, its chat goes with it.");
          return;
        }
        setLost(why);
        setRetry((x) => x + 1);
      }
    }, lost ? POLL_RETRY_MS : document.hidden ? POLL_HIDDEN_MS : writing ? POLL_WRITING_MS : POLL_REQUEST_MS);
    return () => {
      gone = true;
      window.clearTimeout(t);
    };
  }, [chat, polling, msgs, writing, lost, retry]);
  // Back on the page: catch up now rather than at the slower pace.
  useEffect(() => {
    const back = () => { if (!document.hidden) setRetry((x) => x + 1); };
    document.addEventListener("visibilitychange", back);
    return () => document.removeEventListener("visibilitychange", back);
  }, []);
  useEffect(() => {
    if (!writing) setStopping("");
  }, [writing]);

  // Keep the newest words in view, unless you scrolled up to read.
  const onScroll = () => {
    const el = log.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };
  useLayoutEffect(() => {
    const el = log.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [msgs, problem]);

  // The message box grows with what you write (or with its hint, when that takes two lines), up to about eight
  // lines; then it scrolls. A narrower window wraps the words again, so it is measured again then too.
  const fit = useCallback(() => {
    const el = input.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight + 2}px`;
  }, []);
  useLayoutEffect(() => {
    fit();
    const el = input.current;
    if (el && nextCaret.current !== null) {
      el.setSelectionRange(nextCaret.current, nextCaret.current);
      setCaret(nextCaret.current);
      nextCaret.current = null;
    }
  }, [text, placeholder, fit]);
  useEffect(() => {
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [fit]);

  const replace = useCallback((m: ChatMessage) => setMsgs((all) => all.map((x) => (x.id === m.id ? m : x))), []);
  const reload = async () => {
    if (!chat) return;
    try { setMsgs(await chatApi.messages(chat.id)); } catch { /* the toast already said why */ }
  };

  /** Send words to the chat. From the box (Enter or Send) the box empties and keeps the focus; a quick reply pressed
   * from the keyboard puts the focus in the box too, since the reply goes away once it is answered. `choice`: words
   * the model or the editor offered as a quick reply, which never forget anything at once (the server shows a card).
   * `forget`: a "Which one?" button's memory words, sent apart from the message so they are forgotten exactly. */
  const send = async (words: string, fromBox = false, refocus = fromBox, choice = false, forget?: string) => {
    const said = words.trim();
    if (!chat || !said || sendingNow.current || writing || busy) return;
    if (said.length > MAX_CHAT_TEXT) {
      toast(`Keep a message under ${MAX_CHAT_TEXT.toLocaleString("en-US")} characters.`, true);
      return;
    }
    // before Send switches itself off while it sends (which would drop the focus on the page)
    if (refocus) input.current?.focus({ preventScroll: true });
    sendingNow.current = true;
    setSending(true);
    try {
      const r = await chatApi.say(chat.id, said, v?.plan_revision, choice, forget);
      stick.current = true;
      setLost("");
      setMsgs((all) => [...all.filter((m) => m.id !== r.owner.id && m.id !== r.ai.id), r.owner, r.ai]);
      // what was sent leaves the box; anything typed after it while it was sending stays
      if (fromBox) setText((t) => (t.startsWith(words) ? t.slice(words.length).replace(/^\s+/, "") : t));
    } catch (e) {
      toast(errorText(e), true);
    }
    sendingNow.current = false;
    setSending(false);
  };
  const stop = async (e?: ReactMouseEvent) => {
    if (!chat || !writing || stopping === writing.id) return;
    if (e && notTouch(e)) input.current?.focus({ preventScroll: true });  // Stop switches itself off: the box is next
    setStopping(writing.id);
    try {
      if (writing.data?.tool === "change" && writing.data.request?.status === "thinking") replace(await chatApi.discard(chat.id, writing.id));
      else setMsgs(await chatApi.stop(chat.id));
      setLost("");
    } catch (err) {
      setStopping("");
      toast(errorText(err), true);
    }
  };
  const act = async (m: ChatMessage, what: "apply" | "discard") => {
    if (!chat || actingNow.current) return;
    actingNow.current = true;
    setActing(true);
    try {
      const r = await chatApi[what](chat.id, m.id);
      replace(r);
      if (what === "apply") {
        const version = r.data?.request?.applied_revision;
        toast(version ? `Applied as version ${version}. Undo takes it back.` : "Applied. Undo takes it back.");
        onApplied?.();
      }
    } catch (e) {
      toast(errorText(e), true);
      await reload();
    }
    actingNow.current = false;
    setActing(false);
  };
  const decide = async (m: ChatMessage, a: ChatAction, doIt: boolean) => {
    if (!chat || actingNow.current) return;
    actingNow.current = true;
    setActing(true);
    try {
      const r = await chatApi.decide(chat.id, m.id, a.id, doIt);
      const now = (r.data?.pending || []).find((p) => p.id === a.id);
      // a deleted project leaves this page's pins too, as on the Projects page (the saved pins lost it already)
      if (a.tool === "delete_project" && (r.gone || now?.state === "done")) forgetPin(String(a.args.project || ""));
      if (r.gone) {
        toast(`${sentence(now?.result || "Done")} Its chat went with it.`);
        if (alive.current) navigate("#/projects");  // only from its own page: you may have gone somewhere else meanwhile
        return;
      }
      replace(r);
      if (now?.state === "waiting" && doIt && now.result) toast(sentence(now.result), true);  // not yet: press OK again
      else if (now?.state === "failed") toast(sentence(now.result || "It did not work"), true);
      else if (now?.state === "done") {
        toast(sentence(now.result || "Done"));
        if (projectId) onApplied?.();
      }
    } catch (e) {
      toast(errorText(e), true);
      await reload();
    } finally {
      actingNow.current = false;
      setActing(false);
    }
  };
  // Stable handles for the messages (they redraw only when their own message changes while an answer is written).
  const latest = useRef({ act, send, decide });
  latest.current = { act, send, decide };
  const onAct = useCallback((m: ChatMessage, what: "apply" | "discard") => latest.current.act(m, what), []);
  const onSend = useCallback((words: string, keyboard = false, choice = false, forget?: string) =>
    latest.current.send(words, false, keyboard, choice, forget), []);
  const onDecide = useCallback((m: ChatMessage, a: ChatAction, doIt: boolean) => latest.current.decide(m, a, doIt), []);
  // "Clear this chat" goes with the messages, so the dialog cannot give the focus back to it: the conversation takes it.
  const cleared = useRef(false);
  const clear = async () => {
    if (!chat) return;
    await chatApi.clear(chat.id);
    cleared.current = true;
    setMsgs([]);
    toast("The chat is cleared. What ClipForge AI remembers stays (Brain → Memory).");
  };
  useEffect(() => {
    if (clearing || !cleared.current) return;
    cleared.current = false;
    if (focusLost()) log.current?.focus({ preventScroll: true });
  }, [clearing]);

  // ---------------------------------------------------------------- talking to a helper: "@Name …"
  const mention = (a: ChatAgent) => {
    const hit = mentionOf(text, agents);
    const rest = hit ? text.slice(1 + hit.name.length).replace(/^[\s,:;-]+/, "") : text.replace(/^@\S*\s*/, "");
    const next = `@${a.name} ${rest}`;
    setText(next);
    setHush(next);
    nextCaret.current = next.length;
    input.current?.focus();
  };
  const query = text.startsWith("@") && caret >= 1 && !text.slice(0, caret).includes("\n") ? text.slice(1, caret) : null;
  const matches = useMemo(() => {
    if (query === null || query.length > 40) return [];
    const q = query.toLowerCase();
    const starts = helpers.filter((a) => a.name.toLowerCase().startsWith(q));
    const inside = q ? helpers.filter((a) => !starts.includes(a) && a.name.toLowerCase().split(/\s+/).some((w) => w.startsWith(q))) : [];
    return [...starts, ...inside].slice(0, 8);
  }, [query, helpers]);
  const suggesting = focused && matches.length > 0 && hush !== text && !writing;
  useEffect(() => setPick(0), [query]);
  const choose = (a: ChatAgent) => {
    const rest = text.slice(caret).replace(/^\S*/, "").trimStart();
    const next = `@${a.name} ${rest}`;
    setText(next);
    setHush(next);
    nextCaret.current = a.name.length + 2;
  };
  const listId = `${uid}-helpers`;

  const onKey = (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (suggesting) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        setPick((i) => (i + (e.key === "ArrowDown" ? 1 : matches.length - 1)) % matches.length);
        return;
      }
      if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
        e.preventDefault();
        choose(matches[Math.min(pick, matches.length - 1)]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        setHush(text);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(text, true);
    }
  };
  const readCaret = (el: HTMLTextAreaElement) => setCaret(el.selectionStart ?? el.value.length);

  // ---------------------------------------------------------------- what the page shows
  const place = v?.name || (projectId ? chat?.title : "") || "";
  const examples = !chat ? [] : !ready
    ? (projectId ? ["Remember: my intro is 3 seconds", "What do you know?", "How loud should my video be?"]
      : ["Remember: my videos are about hiking", "Never zoom in on faces", "How loud should my video be?"])
    : projectId ? ["What would make this video better?", "Make the opening shorter", "Write a title for this video"]
      : ["What projects do I have?", "Give me 5 hook ideas for my next video", "Remember: my channel is about hiking"];
  const H = tall ? "h2" : "h3";
  const near = text.length >= MAX_CHAT_TEXT - 400;
  const lastId = msgs.length ? msgs[msgs.length - 1].id : "";
  const locked = busy || acting;

  const section = (
    <section className={`cfai${tall ? " tall" : ""}`} aria-labelledby={`${uid}-title`}>
      <div className="cfai-head">
        <div className="cfai-title">
          <H id={`${uid}-title`} className="row"><Icon name="spark" />ClipForge AI</H>
          {ready && ai && <p className="cfai-model"><Icon name={ai.local ? "cpu" : "external"} className="xs" />
            {ai.label}<span aria-hidden="true">·</span>{ai.local ? "on this computer" : "online"}</p>}
        </div>
        {msgs.length > 0 && <button type="button" className="btn btn-small btn-quiet" disabled={!!writing}
          onClick={() => setClearing(true)}><Icon name="trash" />Clear this chat</button>}
      </div>
      {ai?.better && <BetterTip key={ai.better.level} better={ai.better}
        initial={ai.builtin?.task?.level === ai.better.level ? ai.builtin.task : undefined}
        onReady={() => { void open(); toast(`ClipForge AI now talks with ${ai.better?.name} (${ai.better?.model}).`); }} />}
      {ai && !ai.ready && <SetupCard ai={ai} onReady={() => { void open(); toast("ClipForge AI's model is ready. Say hello!"); }} />}
      {problem && <div className="cfai-problem" role="alert"><Icon name="alert" className="sm" /><span className="grow">{problem}</span>
        <button type="button" className="btn btn-small" onClick={() => void open()}><Icon name="refresh" />Try again</button></div>}
      <div ref={log} className="cfai-log" role="log" aria-live={heard ? "polite" : "off"} aria-label="Conversation with ClipForge AI"
        tabIndex={0} onScroll={onScroll}>
        {msgs.length === 0 && !problem && chat && (
          <div className="cfai-welcome">
            <span className="cfai-avatar lg" aria-hidden="true"><Icon name="spark" /></span>
            <p className="cfai-hello">{projectId && place ? `Hi! Let's work on “${place}”.` : "Hi! I'm ClipForge AI."}</p>
            <p className="small muted">{!ready
              ? "I can't really talk until my model is set up, but I already remember what you tell me and answer editing questions from my know-how."
              : projectId ? "Ask me about this video or tell me what to change. I propose a checked change, and nothing changes until you press Apply."
                : "Ask me anything about your videos and your channel, or tell me what to make. I know your projects and what you taught me, and I can do things in ClipForge when you ask."}</p>
            <div className="cfai-chips" role="group" aria-label="Try one of these">
              {examples.map((x) => <button key={x} type="button" className="chip" disabled={sending || locked}
                onClick={(e) => void send(x, false, notTouch(e))}>{x}</button>)}
            </div>
          </div>
        )}
        {msgs.map((m) => m.role === "owner"
          ? <Owner key={m.id} m={m} agents={agents} />
          : <Answer key={m.id} m={m} last={m.id === lastId} busy={locked} sending={sending || !!writing} onAct={onAct} onSend={onSend}
            onDecide={onDecide} />)}
      </div>
      {lost && polling && <p className="cfai-meta"><Icon name="offline" className="xs" />ClipForge is not answering right now; trying again…</p>}
      {helpers.length > 0 && (
        <div className="cfai-helpers-row" role="group" aria-label="Ask a helper">
          <span className="small muted">Ask a helper:</span>
          {helpers.map((a) => (
            <button key={a.id} type="button" className="chip cfai-agent-chip" title={a.role} disabled={!!writing} onClick={() => mention(a)}>
              <span aria-hidden="true">{a.icon || "🤖"}</span>{a.name}</button>
          ))}
        </div>
      )}
      <form className="cfai-compose" onSubmit={(e) => { e.preventDefault(); void send(text, true); }}>
        {suggesting && (
          <ul className="cfai-suggest" role="listbox" id={listId} aria-label="Helpers">
            {matches.map((a, i) => (
              <li key={a.id} id={`${listId}-${i}`} role="option" aria-selected={i === pick}
                onMouseDown={(e) => e.preventDefault()} onClick={() => choose(a)}>
                <span className="cfai-avatar emoji sm" aria-hidden="true">{a.icon || "🤖"}</span>
                <span className="grow"><b>{a.name}</b><span className="block tiny muted clamp-1">{a.role}</span></span>
              </li>
            ))}
          </ul>
        )}
        <span className="sr-only" aria-live="polite">{suggesting
          ? `${matches.length} helper${matches.length === 1 ? "" : "s"} match. Up and down arrows choose, Enter picks.`
          : lost && polling ? "ClipForge is not answering right now; trying again." : ""}</span>
        <label className="sr-only" htmlFor={`${uid}-box`}>{projectId ? "Message to ClipForge AI about this video" : "Message to ClipForge AI"}</label>
        <div className="cfai-input">
          <textarea ref={input} id={`${uid}-box`} rows={1} value={text} maxLength={MAX_CHAT_TEXT} readOnly={!!writing}
            aria-disabled={writing ? true : undefined} disabled={!chat}
            aria-autocomplete="list" aria-controls={suggesting ? listId : undefined}
            aria-activedescendant={suggesting ? `${listId}-${Math.min(pick, matches.length - 1)}` : undefined}
            aria-describedby={`${uid}-hint`} placeholder={placeholder}
            onChange={(e) => { setText(e.target.value); readCaret(e.target); }}
            onSelect={(e) => readCaret(e.currentTarget)} onKeyDown={onKey}
            onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} />
          {/* two different buttons (keys), so a Send that has the focus never turns into a Stop under the next key press */}
          {writing ? (
            <button key="stop" type="button" className="btn" disabled={stopping === writing.id} onClick={(e) => void stop(e)}>
              {stopping === writing.id ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="stop" />}
              {stopping === writing.id ? "Stopping" : "Stop"}</button>
          ) : (
            <button key="send" type="submit" className="btn btn-primary" disabled={!chat || busy || sending || !text.trim()}>
              {sending ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="spark" />}Send</button>
          )}
        </div>
        <div className="cfai-compose-foot">
          <span id={`${uid}-hint`} className="tiny muted">{writing ? "ClipForge AI is answering. Stop ends it early; it keeps what it wrote."
            : helpers.length ? "Enter sends, Shift+Enter makes a new line. Start with @ to talk to a helper."
              : "Enter sends, Shift+Enter makes a new line."}</span>
          {near && <span className={`tiny cfai-count${text.length >= MAX_CHAT_TEXT ? " full" : ""}`}>
            {text.length.toLocaleString("en-US")} / {MAX_CHAT_TEXT.toLocaleString("en-US")}</span>}
        </div>
      </form>
      {clearing && <ConfirmDialog title="Clear this chat?" confirmLabel="Clear the chat" danger onConfirm={clear}
        onClose={() => setClearing(false)}>
        <p>Every message in this chat goes. What ClipForge AI remembers stays; you see it in Brain → Memory.</p>
      </ConfirmDialog>}
    </section>
  );
  if (!side) return section;
  return (
    <div className="cfai-page">
      {section}
      <HelpersSide agents={agents} ready={ready || !chat} disabled={!!writing || !chat} onAsk={mention} />
    </div>
  );
}

/** Your message, with the helper it names ("@Critic …") marked. */
const Owner = memo(function Owner({ m, agents }: { m: ChatMessage; agents: ChatAgent[] }) {
  const hit = mentionOf(m.text, agents);
  return (
    <div className="cfai-turn owner">
      <div className="cfai-msg owner">
        <span className="sr-only">You said: </span>
        <p>{hit ? <><span className="cfai-mention">@{hit.name}</span>{m.text.slice(1 + hit.name.length)}</> : m.text}</p>
      </div>
    </div>
  );
});

/** Sends words to the chat; `keyboard`: pressed from the keyboard, so the focus goes to the message box; `choice`: a
 * quick reply the model or the editor wrote. */
type SendWords = (words: string, keyboard?: boolean, choice?: boolean, forget?: string) => Promise<void>;

/** ClipForge AI's answer, or a helper's when you talked to it with @. It is drawn again only when it changes. */
const Answer = memo(function Answer({ m, last, busy, sending, onAct, onSend, onDecide }: {
  m: ChatMessage; last: boolean; busy: boolean; sending: boolean;
  onAct: (m: ChatMessage, what: "apply" | "discard") => Promise<void>; onSend: SendWords;
  onDecide: (m: ChatMessage, a: ChatAction, doIt: boolean) => Promise<void>;
}) {
  const d: ChatData = m.data || {};
  const agent = m.role === "agent" ? d.agent || { id: "", name: "Helper", icon: "🤖" } : null;
  const thinking = m.status === "thinking";
  const r = d.request;
  const live = thinking ? d.helper_live : undefined;
  // buttons to pages in the app; one to the page you are on (this video, from its own chat) would go nowhere
  const links = (d.links || []).filter((l) => typeof l?.href === "string" && l.href.startsWith("#/") && l.href !== window.location.hash);
  const ask = !thinking && last ? d.ask : undefined;
  const remembered = d.remembered || [];
  return (
    <div className={`cfai-turn ${agent ? "agent" : "ai"}`}>
      <span className={`cfai-avatar${agent ? " emoji" : ""}`} aria-hidden="true">{agent ? agent.icon || "🤖" : <Icon name="spark" />}</span>
      <div className={`cfai-msg ai${m.status === "failed" ? " failed" : ""}`} aria-busy={thinking || undefined}>
        <span className="cfai-who">{agent ? <>{agent.name}<span className="muted"> · helper</span></> : "ClipForge AI"}</span>
        {(d.steps || []).length > 0 && <Steps steps={d.steps || []} />}
        {m.text ? <div className="cfai-text"><Lines text={m.text} /></div> : null}
        {thinking && !live && <Typing quiet={!!m.text} />}
        {(d.helpers || []).map((h, i) => <Helper key={i} h={h} />)}
        {live && <Helper h={{ ...live, ok: true }} live />}
        {r && <Proposal r={r} full={d.tool !== "change"} busy={busy} onAct={(what) => onAct(m, what)} onSend={onSend} />}
        {(d.pending || []).map((a) => <Action key={a.id} a={a} disabled={busy || thinking} onDecide={(doIt) => onDecide(m, a, doIt)} />)}
        {links.length > 0 && <div className="cfai-links">
          {links.map((l, i) => <a key={i} className="btn btn-small" href={l.href}><Icon name="chev" />{l.label}</a>)}</div>}
        {ask && ask.choices.length > 0 && <Ask ask={ask} said={m.text} disabled={sending || busy} onSend={onSend} />}
        {d.tool === "forget" && (d.candidates || []).length > 0 && <div className="cfai-chips" role="group" aria-label="Forget one">
          {(d.candidates || []).map((c) => <button key={c.id} type="button" className="btn btn-small ask-choice" disabled={busy || sending}
            onClick={(e) => void onSend(`forget “${c.text}”`, notTouch(e), false, c.text)}><Icon name="trash" />Forget “{c.text}”</button>)}
        </div>}
        {(remembered.length > 0 || (d.tool === "remember" && d.memory)) && <div className="cfai-chips">
          {remembered.map((mem) => <Remembered key={mem.id} mem={mem} />)}
          {d.tool === "remember" && d.memory && <Remembered mem={d.memory} short />}
        </div>}
        {!thinking && <Meta d={d} failed={m.status === "failed"} />}
      </div>
    </div>
  );
});

/** The dots while an answer is written; "Thinking…" before its first words. */
function Typing({ quiet = false, label = "Thinking…" }: { quiet?: boolean; label?: string }) {
  return (
    <p className={`cfai-typing${quiet ? " quiet" : ""}`}>
      <span className="cfai-dots" aria-hidden="true"><i /><i /><i /></span>
      {quiet ? <span className="sr-only">Still writing</span> : <span>{label}</span>}
    </p>
  );
}

/** What ClipForge AI looked at or did while answering. */
function Steps({ steps }: { steps: ChatStep[] }) {
  return (
    <ul className="cfai-steps" aria-label="What it did">
      {steps.map((s, i) => (
        <li key={i} className={s.ok ? undefined : "bad"}>
          <Icon name={s.ok ? "check" : "alert"} className="xs" />
          <span>{s.label}{!s.ok && s.why ? `: ${s.why}` : ""}</span>
        </li>
      ))}
    </ul>
  );
}

/** A helper agent's work inside the answer (its own card; long work folds). */
function Helper({ h, live = false }: { h: HelperWork; live?: boolean }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const long = !live && (h.text.length > 600 || h.text.split("\n").length > 9);
  return (
    <div className={`cfai-helper${h.ok ? "" : " failed"}`}>
      <div className="cfai-helper-head">
        <span className="cfai-avatar emoji sm" aria-hidden="true">{h.agent?.icon || "🤖"}</span>
        <b>{h.agent?.name || "Helper"}</b>
        <span className="tiny muted">{live ? "is working on it" : h.ok ? "helped with this" : "could not help"}</span>
      </div>
      {h.task && <p className="tiny muted">Its job: {h.task}</p>}
      {(h.steps || []).length > 0 && <Steps steps={h.steps || []} />}
      <div id={id} className={`cfai-helper-body${long && !open ? " folded" : ""}`}>
        {h.text ? <Lines text={h.text} /> : null}
        {live && <Typing quiet={!!h.text} label="Working…" />}
      </div>
      {long && <button type="button" className="link-btn small" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        {open ? "Show less" : "Show all of it"}</button>}
    </div>
  );
}

/** A change ClipForge AI proposed for this video: Apply as a new version, Discard, or answer its question. Old change
 * messages already say the proposal in their words (`full` false): the card adds its state and buttons. */
function Proposal({ r, full, busy, onAct, onSend }: {
  r: ChangeRequest; full: boolean; busy: boolean; onAct: (what: "apply" | "discard") => Promise<void>;
  onSend: SendWords;
}) {
  const p = r.proposal || {};
  const changes = p.changes || [];
  const root = useRef<HTMLDivElement>(null);
  // after Apply, Discard or Cancel the focus stays here: on a button still there, or on the card that says what happened
  const pressed = useRefocus(!busy, () => root.current?.querySelector<HTMLElement>("button:not(:disabled)") || root.current, r.status);
  const act = (what: "apply" | "discard") => {
    pressed();
    void onAct(what);
  };
  return (
    <div ref={root} className="cfai-proposal" tabIndex={-1}>
      <div className="row wrap">
        <Pill tone={TONE[r.status]}>{WORD[r.status]}</Pill>
        <span className="small muted">{r.source !== "ai" ? "Understood without a model" : r.status === "thinking" ? `Asking ${r.provider}` : `Answered by ${r.provider}`}</span>
      </div>
      {full && r.status === "thinking" && <p className="small row"><span className="inline-spinner" aria-hidden="true" />{r.message || "Working out the change…"}</p>}
      {full && r.status === "ready" && <>
        {p.summary && <p>{p.summary}</p>}
        {changes.length > 0 && <ul className="cfai-list">{changes.slice(0, 12).map((c, i) => <li key={i}>{c}</li>)}</ul>}
      </>}
      {full && r.status === "question" && <p>{r.message || p.question}</p>}
      {full && !["thinking", "ready", "question"].includes(r.status) && r.message && <p className="small">{r.message}</p>}
      {r.status === "ready" && <div className="row wrap">
        <button type="button" className="btn btn-primary btn-small" disabled={busy} onClick={() => act("apply")}><Icon name="check" />Apply as a new version</button>
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => act("discard")}>Discard</button>
      </div>}
      {r.status === "thinking" && <div><button type="button" className="btn btn-small" disabled={busy} onClick={() => act("discard")}><Icon name="stop" />Cancel</button></div>}
      {r.status === "question" && (p.choices || []).length > 0 && <div className="cfai-chips" role="group" aria-label="Choose one">
        {(p.choices || []).map((c) => <button key={c.request} type="button" className="btn btn-small ask-choice" disabled={busy}
          onClick={(e) => void onSend(c.request, notTouch(e), true)}>{c.label}</button>)}
      </div>}
    </div>
  );
}

/**
 * A button that switches itself off while its work runs (or goes away after it) drops the focus on the page, and a
 * keyboard or screen reader user loses their place. Call the returned function on the press: once `done`, the focus
 * goes to `to()`, unless something else took it meanwhile. `key` is what changes when the work is done.
 */
function useRefocus(done: boolean, to: () => HTMLElement | null | undefined, key: unknown) {
  const was = useRef(false);
  useEffect(() => {
    if (!was.current || !done) return;
    was.current = false;
    if (focusLost()) to()?.focus({ preventScroll: true });
  }, [done, key]); // eslint-disable-line react-hooks/exhaustive-deps
  return useCallback(() => { was.current = true; }, []);
}

/** A change or delete waiting for your OK: what it does, then OK or No; afterwards what happened. A press that could
 * not do it yet keeps the buttons and says why in a note ("still stopping, press OK again in a moment"). */
function Action({ a, disabled, onDecide }: { a: ChatAction; disabled: boolean; onDecide: (doIt: boolean) => void }) {
  const danger = a.risk === "delete";
  const waiting = a.state === "waiting";
  const after = a.state === "waiting" ? null : ACTION_STATE[a.state] || ACTION_STATE.blocked;
  const why = a.state === "blocked" ? a.blocked || a.result : a.result;
  const ok = useRef<HTMLButtonElement>(null);
  const outcome = useRef<HTMLParagraphElement>(null);
  // after the press the focus goes to what happened, or back to OK when it still waits
  const pressed = useRefocus(!disabled, () => (waiting ? ok.current : outcome.current), `${a.state} ${a.result}`);
  const press = (doIt: boolean) => {
    pressed();
    onDecide(doIt);
  };
  // a question ("Remember “…”?") is marked as one; anything else as the change or delete it is
  const icon: IconName = danger ? "trash" : /\?["”’)]*$/.test(a.label.trim()) ? "question" : "edit";
  return (
    <div className={`cfai-action${danger ? " danger" : ""} ${a.state}`} role="group" aria-label={a.label}>
      <p className="cfai-action-label"><Icon name={icon} className="sm" /><b>{a.label}</b></p>
      {(a.detail || []).length > 0 && <ul className="cfai-action-detail">{a.detail.map((x, i) => <li key={i}>{x}</li>)}</ul>}
      {after ? (
        <p ref={outcome} tabIndex={-1} className={`cfai-action-state ${after.tone}`}><Icon name={after.icon} className="xs" />
          {a.state === "done" && why ? sentence(why) : `${after.word}${why ? `: ${sentence(why)}` : "."}`}</p>
      ) : (
        <>
          {/* pressed, but not yet possible: the toast said it too; the note stays until the next press */}
          {a.result && <p className="cfai-action-note"><Icon name="clock" className="xs" /><span>{sentence(a.result)}</span></p>}
          <div className="row wrap">
            <button ref={ok} type="button" className={`btn btn-small ${danger ? "btn-danger" : "btn-primary"}`} disabled={disabled}
              onClick={() => press(true)}><Icon name={danger ? "trash" : "check"} />{danger ? "OK, delete it" : "OK, do it"}</button>
            <button type="button" className="btn btn-small" disabled={disabled} onClick={() => press(false)}>No</button>
            {!a.result && <span className="tiny muted">Nothing happens until you press OK.</span>}
          </div>
        </>
      )}
    </div>
  );
}

/** ClipForge AI's question with its choices: one press answers. */
function Ask({ ask, said, disabled, onSend }: { ask: ChatAsk; said: string; disabled: boolean; onSend: SendWords }) {
  const question = ask.question && !said.includes(ask.question.slice(0, 40)) ? ask.question : "";
  return (
    <div className="cfai-ask">
      {question && <p className="cfai-ask-q">{question}</p>}
      <div className="cfai-chips" role="group" aria-label={ask.question || "Quick replies"}>
        {ask.choices.map((c) => <button key={c} type="button" className="chip" disabled={disabled}
          onClick={(e) => void onSend(c, notTouch(e), true)}>{c}</button>)}
      </div>
    </div>
  );
}

/** "Remembered: …" with Undo, which forgets that memory only while it is as this answer added it (the server checks:
 * revision 1 and the same words); one written over or changed since stays. `short`: the answer already says what was
 * remembered. A chip an earlier build saved for a memory it wrote over (revision above 1) has no Undo. */
function Remembered({ mem, short = false }: { mem: Memory; short?: boolean }) {
  const [state, setState] = useState<"kept" | "busy" | "gone" | "changed">("kept");
  const added = (mem.revision ?? 1) === 1;
  const chip = useRef<HTMLSpanElement>(null);
  const undoButton = useRef<HTMLButtonElement>(null);
  const pressed = useRefocus(state !== "busy", () => (state === "gone" || state === "changed" ? chip.current : undoButton.current), state);
  const undo = async () => {
    pressed();
    setState("busy");
    try {
      await memoryApi.undo(mem.id, mem.text);
      setState("gone");
      toast(`Forgotten: “${mem.text}”.`);
    } catch (e) {
      if (/not found/i.test(errorText(e))) {
        setState("gone");
        toast("That was already forgotten.");
      } else if (/changed since/i.test(errorText(e))) {
        setState("changed");
        toast(errorText(e));
      } else {
        setState("kept");
        toast(errorText(e), true);
      }
    }
  };
  const gone = state === "gone";
  const changed = state === "changed";
  return (
    <span ref={chip} tabIndex={-1} className={`cfai-remembered${gone ? " gone" : ""}`}>
      <Icon name={gone ? "x" : "check"} className="xs" />
      <span>{gone ? `Forgotten: “${mem.text}”` : changed ? "Changed since this answer: see Brain → Memory"
        : short ? "Saved to your memory" : `Remembered: “${mem.text}”`}</span>
      {!gone && !changed && added && <button ref={undoButton} type="button" className="link-btn" disabled={state === "busy"}
        aria-label={`Undo: forget “${mem.text}”`} onClick={() => void undo()}>Undo</button>}
    </span>
  );
}

/** What the answer used (memories, know-how) and where your words went, small. */
function Meta({ d, failed }: { d: ChatData; failed: boolean }) {
  const used = d.used || [];
  const know = d.knowhow || [];
  const shows = ["change", "answer", "explain", "talk", "plan"].includes(d.tool || "");
  const sent = d.sent || d.request?.sent || "";
  return (
    <>
      {shows && used.length > 0 && <p className="cfai-meta">From your brain: {used.map((m) => `[${m.kind}] ${m.text}`).join("; ")}</p>}
      {shows && know.length > 0 && <p className="cfai-meta">From its know-how: {know.map((k) => k.title.toLowerCase()).join("; ")}</p>}
      {sent && !failed && <p className="cfai-meta"><Icon name={d.remote ? "external" : "shield"} className="xs" />{sent}</p>}
    </>
  );
}

/** No model yet: the built-in one in one press (free, on this computer), or another AI helper in Settings. */
function SetupCard({ ai, onReady }: { ai: ChatAi; onReady: () => void }) {
  const id = useId();
  const b = ai.builtin;
  const { task, start, cancel, busy } = useBuiltinInstall(b?.task, onReady);
  const level = b ? b.levels.find((l) => l.id === b.recommended) || b.levels.find((l) => l.recommended) || b.levels[0] : undefined;
  const running = task.state === "running";
  return (
    <section className="cfai-setup" aria-labelledby={id}>
      <p id={id} className="cfai-setup-title"><Icon name="cpu" />ClipForge AI needs its model to talk</p>
      {!b ? (
        <p className="small">Choose the model it thinks with in <a className="textlink" href="#/settings/ai">Settings → ClipForge AI</a>.
          Until then it remembers what you tell it and answers editing questions from its know-how.</p>
      ) : !b.supported ? (
        <p className="small">The built-in model does not run on this computer. You can still choose another AI helper (Ollama,
          LM Studio or a free online key) in <a className="textlink" href="#/settings/ai">Settings → ClipForge AI</a>.</p>
      ) : (
        <>
          <p className="small">Download the built-in model: it is free, it runs on this computer and what you say never leaves it.
            {level && !level.installed ? ` It is about ${gbText(level.download_bytes)}, downloaded once.` : ""}
            {level ? ` ${level.name} (${level.model}) is the one that fits this computer.` : ""}</p>
          {running ? <BuiltinProgress t={task} onCancel={() => void cancel()} /> : (
            <div className="row wrap">
              <button type="button" className="btn btn-primary" disabled={busy || !level} onClick={() => level && void start(level.id)}>
                <Icon name="download" />{level?.installed ? "Use the built-in model"
                  : task.state === "failed" || task.state === "canceled" ? "Download again (it resumes)" : "Download the built-in model"}</button>
              <a className="btn btn-quiet" href="#/settings/ai">Other AI helpers</a>
            </div>
          )}
          {task.state === "failed" && <p className="error-text" role="alert"><Icon name="alert" className="sm" />{task.error || "The download stopped."}</p>}
        </>
      )}
    </section>
  );
}

/** The built-in model could talk better on this computer: one press sets the better level up. */
function BetterTip({ better, initial, onReady }: { better: NonNullable<ChatAi["better"]>; initial?: BuiltinTask; onReady: () => void }) {
  const key = `clipforge.cfai.tip.${better.level}`;
  const [hidden, setHidden] = useState(() => {
    try { return localStorage.getItem(key) === "hidden"; } catch { return false; }
  });
  const { task, start, cancel, busy } = useBuiltinInstall(initial, onReady);
  const running = task.state === "running";
  if (hidden && !running) return null;
  const notNow = () => {
    setHidden(true);
    try { localStorage.setItem(key, "hidden"); } catch { /* shown again next time */ }
  };
  return (
    <div className="cfai-tip" role="note">
      <Icon name="spark" className="sm" />
      <div className="grow stack-2">
        <p className="small">Your computer can run {better.name} ({better.model}), which talks better.
          {better.installed ? " It is already downloaded." : ` It is a ${gbText(better.download_bytes)} download, once.`}</p>
        {running && <BuiltinProgress t={task} onCancel={() => void cancel()} />}
        {task.state === "failed" && <p className="error-text small"><Icon name="alert" className="sm" />{task.error || "The download stopped."}</p>}
      </div>
      {!running && <div className="row">
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => void start(better.level)}>
          {task.state === "failed" ? "Try again" : "Set it up"}</button>
        <button type="button" className="btn btn-small btn-quiet" onClick={notNow}>Not now</button>
      </div>}
    </div>
  );
}

/** Brain → Talk: the switched-on helpers beside the chat, each one press from "@Name". Without a model they are
 * listed but cannot be asked yet (they think with the same model). */
function HelpersSide({ agents, ready, disabled, onAsk }: {
  agents: ChatAgent[]; ready: boolean; disabled: boolean; onAsk: (a: ChatAgent) => void;
}) {
  const id = useId();
  return (
    <aside className="cfai-side" aria-labelledby={id}>
      <h2 id={id}>Your helpers</h2>
      <p className="small muted">{ready
        ? "Specialists that work with ClipForge AI. It hands them jobs; start a message with @ and a name to talk to one yourself."
        : "Specialists that work with ClipForge AI. They think with its model, so they start working once that model is set up."}</p>
      {agents.length > 0 ? (
        <ul className="cfai-side-list">
          {agents.map((a) => (
            <li key={a.id}>
              <span className="cfai-avatar emoji" aria-hidden="true">{a.icon || "🤖"}</span>
              <span className="grow"><b className="block">{a.name}</b><span className="small muted">{a.role}</span></span>
              {ready && <button type="button" className="btn btn-small" disabled={disabled} aria-label={`Talk to ${a.name}`}
                onClick={() => onAsk(a)}>@</button>}
            </li>
          ))}
        </ul>
      ) : <p className="small">No helper is switched on yet.</p>}
      <a className="btn btn-small" href="#/brain/agents"><Icon name="sliders" />{agents.length ? "Manage helpers" : "Add a helper"}</a>
    </aside>
  );
}
