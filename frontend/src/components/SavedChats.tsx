import { useCallback, useEffect, useId, useRef, useState } from "react";
import { errorText } from "../api";
import { chatApi, ChatWork, SavedChat, WorkState } from "../brain";
import { ConfirmDialog, Icon, toast } from "./ui";

/** How old a chat's last message is, in a few words ("5 min ago", "Tue"). */
function when(ts: number): string {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * Talk to AI's saved chats: start a new one, switch between them, rename or delete one. They are kept by ClipForge
 * (not this browser), so they are there after a restart; what ClipForge AI remembers is shared by all of them.
 * `current` is the chat on screen; `seen` changes when it may have a new title (after an answer).
 */
export function SavedChats({ current, seen, disabled, onPick }: {
  current: string; seen: string; disabled: boolean; onPick: (id: string) => void;
}) {
  const id = useId();
  const [chats, setChats] = useState<SavedChat[] | null>(null);
  const [naming, setNaming] = useState("");
  const [name, setName] = useState("");
  const [removing, setRemoving] = useState<SavedChat | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      setChats(await chatApi.list());
    } catch (e) {
      toast(errorText(e), true);
    }
  }, []);
  useEffect(() => { void load(); }, [load, current, seen]);

  const create = async () => {
    setBusy(true);
    try {
      const made = await chatApi.create();
      await load();
      onPick(made.id);
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setBusy(false);
    }
  };
  const rename = async (c: SavedChat) => {
    const title = name.trim();
    setNaming("");
    if (!title || title === c.title) return;
    try {
      await chatApi.rename(c.id, title);
      await load();
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const remove = async () => {
    const c = removing;
    setRemoving(null);
    if (!c) return;
    try {
      await chatApi.remove(c.id);
      const left = (chats || []).filter((x) => x.id !== c.id);
      setChats(left);
      if (c.id === current) onPick(left[0]?.id || "");
      toast(`Deleted “${c.title}”.`);
    } catch (e) {
      toast(errorText(e), true);
    }
  };

  return (
    <section className="cfai-side cfai-chats" aria-labelledby={id}>
      <div className="row cfai-chats-head">
        <h2 id={id} className="grow">Chats</h2>
        <button type="button" className="btn btn-small" disabled={busy || disabled} onClick={() => void create()}>
          <Icon name="plus" />New chat</button>
      </div>
      {chats === null ? <p className="small muted">Loading…</p> : chats.length === 0
        ? <p className="small muted">Your chats show here.</p> : (
          <ul className="cfai-chat-list">
            {chats.map((c) => (
              <li key={c.id} className={c.id === current ? "on" : ""}>
                {naming === c.id ? (
                  <form className="cfai-chat-name" onSubmit={(e) => { e.preventDefault(); void rename(c); }}>
                    <label className="sr-only" htmlFor={`${id}-${c.id}`}>New name for this chat</label>
                    <input id={`${id}-${c.id}`} autoFocus value={name} maxLength={80} onChange={(e) => setName(e.target.value)}
                      onBlur={() => void rename(c)} onKeyDown={(e) => { if (e.key === "Escape") setNaming(""); }} />
                  </form>
                ) : (
                  <button type="button" className="cfai-chat-pick" aria-current={c.id === current ? "true" : undefined}
                    disabled={disabled && c.id !== current} onClick={() => onPick(c.id)}>
                    <b className="block clamp-1">{c.title}</b>
                    <span className="tiny muted clamp-1">{c.messages ? `${c.messages} message${c.messages === 1 ? "" : "s"} · ${when(c.updated_at)}`
                      : "No messages yet"}</span>
                  </button>
                )}
                {naming !== c.id && <span className="cfai-chat-tools">
                  <button type="button" className="btn btn-small btn-quiet btn-icon" aria-label={`Rename “${c.title}”`}
                    onClick={() => { setNaming(c.id); setName(c.title); }}><Icon name="edit" /></button>
                  <button type="button" className="btn btn-small btn-quiet btn-icon" aria-label={`Delete “${c.title}”`}
                    disabled={disabled && c.id === current} onClick={() => setRemoving(c)}><Icon name="trash" /></button>
                </span>}
              </li>
            ))}
          </ul>
        )}
      {removing && <ConfirmDialog title={`Delete “${removing.title}”?`} confirmLabel="Delete the chat" danger
        onConfirm={() => void remove()} onClose={() => setRemoving(null)}>
        <p>Its messages go. What ClipForge AI remembers stays; you see it in Brain → Memory.</p>
      </ConfirmDialog>}
    </section>
  );
}

const WORK_POLL_MS = 2500;
const WORK_WORDS: Record<WorkState["state"], string> = {
  queued: "Queued", running: "Running", completed: "Completed", failed: "Failed", canceled: "Canceled",
};

/** Work a command queued (a render, a project made again, a post moved), as it is now: queued, running (with how
 * far), completed, failed or canceled. It asks ClipForge every few seconds until the state is final. */
export function WorkChip({ w }: { w: ChatWork }) {
  const [s, setS] = useState<WorkState | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    let t = 0;
    const read = async () => {
      try {
        const now = await chatApi.work(w.kind, w.id);
        if (!alive.current) return;
        setS(now);
        if (["completed", "failed", "canceled"].includes(now.state)) return;
      } catch {
        if (!alive.current) return;
      }
      t = window.setTimeout(read, document.hidden ? WORK_POLL_MS * 3 : WORK_POLL_MS);
    };
    void read();
    return () => { alive.current = false; window.clearTimeout(t); };
  }, [w.kind, w.id]);
  const state = s?.state || "queued";
  const pct = state === "running" && s && s.progress > 0 ? ` ${Math.round(s.progress * 100)}%` : "";
  return (
    <div className={`cfai-work ${state}`} role="status">
      <span className="cfai-work-dot" aria-hidden="true">{state === "completed" ? <Icon name="check" className="xs" />
        : state === "failed" ? <Icon name="alert" className="xs" /> : state === "running" ? <span className="inline-spinner" /> : null}</span>
      <span className="grow"><b>{w.label}</b>: {WORK_WORDS[state]}{pct}
        {s?.message && state !== "completed" && <span className="block tiny muted">{s.message}</span>}</span>
      {s?.href && s.href !== window.location.hash && <a className="btn btn-small btn-quiet" href={s.href}>Open</a>}
    </div>
  );
}
