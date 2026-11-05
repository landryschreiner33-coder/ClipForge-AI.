import { useEffect, useRef, useState } from "react";
import { errorText } from "../api";
import { Icon, Pill, toast } from "./ui";
import { ChangeRequest, studio, Video } from "../studio";

const TONE: Record<ChangeRequest["status"], "good" | "warn" | "bad" | "neutral"> = {
  thinking: "neutral", ready: "good", question: "warn", unsupported: "neutral", invalid: "bad", failed: "bad",
  canceled: "neutral", applied: "good", stale: "warn",
};
const WORD: Record<ChangeRequest["status"], string> = {
  thinking: "Working on it", ready: "Ready to check", question: "Question", unsupported: "Not done", invalid: "Refused",
  failed: "Failed", canceled: "Canceled", applied: "Applied", stale: "Out of date",
};

function fmt(ms: number) {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** "Tell the editor what to change": a request becomes a proposal you check before anything changes. Common requests
 * are understood without AI; anything else goes to the AI service in Settings (text only), when one is set up. Apply
 * saves a new version that Undo reverts. */
export function AskForChange({ v, busy, onApplied }: { v: Video; busy: boolean; onApplied: () => void }) {
  const [text, setText] = useState("");
  const [req, setReq] = useState<ChangeRequest | null>(null);
  const [working, setWorking] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (req?.status !== "thinking") return;
    timer.current = window.setTimeout(async () => {
      try { setReq(await studio.changeRequest(req.id)); } catch (e) { toast(errorText(e), true); }
    }, 800);
  }, [req]);

  const ask = async (words: string) => {
    if (!words.trim()) return;
    setWorking(true);
    try { setReq(await studio.askForChange(v.id, words.trim(), v.plan_revision)); } catch (e) { toast(errorText(e), true); }
    setWorking(false);
  };
  const apply = async () => {
    if (!req) return;
    setWorking(true);
    try {
      const r = await studio.applyChange(req.id);
      setReq(r);
      setText("");
      toast(`Applied as version ${r.applied_revision}. Undo takes it back.`);
      onApplied();
    } catch (e) {
      toast(errorText(e), true);
      try { setReq(await studio.changeRequest(req.id)); } catch { /* the toast already says why */ }
    }
    setWorking(false);
  };
  const p = req?.proposal;
  const by = !req ? "" : req.source !== "ai" ? "Understood without AI"
    : req.status === "thinking" ? `Asking ${req.provider}` : `Answered by ${req.provider}`;
  return (
    <div className="ask-change stack-2">
      <form className="ask-row" onSubmit={(e) => { e.preventDefault(); void ask(text); }}>
        <label className="field grow"><span>Tell the editor what to change</span>
          <input value={text} maxLength={500} onChange={(e) => setText(e.target.value)}
            placeholder="For example: move the summit part before lunch" /></label>
        <button type="submit" className="btn" disabled={busy || working || !text.trim() || req?.status === "thinking"}>Propose</button>
      </form>
      <p className="small muted">Nothing changes until you press Apply. Common requests are understood without AI; anything
        else goes to the AI service in Settings → AI, if one is set up, as text only (never the video or sound).</p>
      {req && (
        <section className="ask-result stack-2" aria-live="polite" aria-label="Proposed change">
          <div className="row wrap">
            <Pill tone={TONE[req.status]}>{WORD[req.status]}</Pill>
            <span className="small muted">“{req.text}” · {by}</span>
          </div>
          {req.status === "thinking" && <>
            <p className="small">{req.message}…</p>
            {req.sent && <p className="small muted">{req.sent}</p>}
            <div><button type="button" className="btn btn-small" onClick={async () => setReq(await studio.cancelChange(req.id))}><Icon name="stop" />Cancel</button></div>
          </>}
          {req.status === "ready" && p && <>
            {p.summary && <p>{p.summary}</p>}
            <ul className="small change-list">{(p.changes || []).map((c) => <li key={c}>{c}</li>)}</ul>
            {p.duration_ms && p.duration_ms[0] !== p.duration_ms[1] && <p className="small muted">Length {fmt(p.duration_ms[0])} → {fmt(p.duration_ms[1])}</p>}
            {req.sent && <p className="small muted">{req.sent}</p>}
            <div className="row wrap">
              <button type="button" className="btn btn-primary" disabled={busy || working} onClick={() => void apply()}><Icon name="check" />Apply as a new version</button>
              <button type="button" className="btn" disabled={working} onClick={async () => setReq(await studio.cancelChange(req.id))}>Discard</button>
            </div>
          </>}
          {req.status === "question" && <>
            <p>{req.message}</p>
            {(p?.choices || []).length > 0 && <div className="row wrap" role="group" aria-label="Choose one">
              {(p?.choices || []).map((c) => <button key={c.request} type="button" className="btn btn-small ask-choice" disabled={working}
                onClick={() => { setText(c.request); void ask(c.request); }}>{c.label}</button>)}
            </div>}
            {!(p?.choices || []).length && <p className="small muted">Answer by asking again with more detail.</p>}
          </>}
          {!["thinking", "ready", "question"].includes(req.status) && <p className={req.status === "failed" || req.status === "invalid" ? "small error-text" : "small"}>{req.message}</p>}
        </section>
      )}
    </div>
  );
}
