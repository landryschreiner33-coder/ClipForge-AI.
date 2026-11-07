import { DragEvent, useRef, useState } from "react";
import { errorText } from "../api";
import { Script, studio } from "../studio";
import { Icon } from "./ui";
import "./longVideo.css";

const ACCEPT = ".txt,.text,.md,.markdown,.docx,.pdf,.fdx,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

/** Your script: drop a file (.txt, .md, .docx, .pdf, .fdx) or paste the text. ClipForge reads it into numbered
 * lines here (nothing is stored until the video is made) and the parent gets the result, or null when it is
 * taken away. */
export function ScriptDrop({ value, onChange, compact }: { value: Script | null; onChange: (s: Script | null) => void; compact?: boolean }) {
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [text, setText] = useState("");
  const [pasting, setPasting] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const read = async (source: File | { text: string }) => {
    setBusy(true);
    setProblem("");
    try {
      onChange(await studio.parseScript(source));
      setPasting(false);
      setText("");
    } catch (e) {
      setProblem(errorText(e));
    }
    setBusy(false);
  };
  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) void read(f);
  };
  if (value) {
    const c = value.counts;
    return (
      <div className="script-drop" aria-live="polite">
        <div className="file-row">
          <Icon name="edit" />
          <div className="break"><b className="clamp-1">{value.filename}</b>
            <span className="block small muted">{c.lines} spoken line{c.lines === 1 ? "" : "s"} · {c.words} words{c.headings ? ` · ${c.headings} heading${c.headings === 1 ? "" : "s"} (chapters)` : ""}{c.directions ? ` · ${c.directions} direction${c.directions === 1 ? "" : "s"} (never said)` : ""}</span></div>
          <div className="row-actions">
            <button type="button" className="btn btn-small" onClick={() => input.current?.click()}>Replace</button>
            <button type="button" className="btn btn-small" onClick={() => onChange(null)}>Take it away</button>
          </div>
        </div>
        <input ref={input} type="file" accept={ACCEPT} hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void read(f); e.target.value = ""; }} />
        {!compact && <ol className="script-lines small" aria-label="The script as ClipForge read it">
          {value.lines.slice(0, 200).map((ln) => (
            <li key={ln.n} className={`script-line ${ln.kind}`}><span className="n">{ln.n}</span><span>{ln.kind === "direction" ? `[${ln.text}]` : ln.speaker && ln.kind === "line" ? `${ln.speaker}: ${ln.text}` : ln.text}</span></li>
          ))}
          {value.lines.length > 200 && <li className="script-line"><span className="n" /><span className="muted">… and {value.lines.length - 200} more lines</span></li>}
        </ol>}
        {problem && <p className="error-text small">{problem}</p>}
      </div>
    );
  }
  return (
    <div className="script-drop">
      <div className={`drop ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop}>
        <Icon name="edit" size={28} />
        <span>{busy ? "Reading the script…" : "Drop your script here (.txt, .md, .docx, .pdf or Final Draft)"}</span>
        <div className="row-actions wrap">
          <button type="button" className="btn" disabled={busy} onClick={() => input.current?.click()}>Choose a file</button>
          <button type="button" className="btn" disabled={busy} onClick={() => setPasting((p) => !p)}>{pasting ? "Cancel" : "Paste the text"}</button>
        </div>
        <input ref={input} type="file" accept={ACCEPT} hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void read(f); e.target.value = ""; }} />
      </div>
      {pasting && <div className="stack-2">
        <textarea value={text} aria-label="Your script" placeholder="Paste or type your script, one line or paragraph per thing you say. A line starting with # is a heading (a chapter)." onChange={(e) => setText(e.target.value)} />
        <button type="button" className="btn btn-small" disabled={busy || !text.trim()} onClick={() => read({ text })}>Use this text</button>
      </div>}
      {problem && <p className="error-text small">{problem}</p>}
    </div>
  );
}
