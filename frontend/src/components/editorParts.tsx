import { KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { fmtPrecise, Word } from "../api";
import { Segmented } from "./ui";

// ------------------------------------------------------------------ is the saved edit in the video?
/*
 * The renderer stores `render_info.edit_hash`: sha1(json.dumps(edit, sort_keys=True))[:12] of the edit it rendered
 * (clipfoundry/pipeline/render.py, edit_hash). Computing the same fingerprint of the saved edit tells, from the
 * backend's own record, whether the saved changes are in the video yet. Python's json.dumps is reproduced: ", " and
 * ": " separators, sorted keys, non-ASCII escaped, and Python's float notation.
 */
function pyNumber(n: number): string {
  if (Number.isNaN(n)) return "NaN";
  if (!Number.isFinite(n)) return n > 0 ? "Infinity" : "-Infinity";
  if (Number.isInteger(n)) return String(n); // edits arrive as JSON from this page, so whole numbers are ints
  const abs = Math.abs(n);
  if (abs < 1e-4 || abs >= 1e16) {
    const [m, e] = n.toExponential().split("e");
    const exp = Number(e);
    return `${m}e${exp < 0 ? "-" : "+"}${String(Math.abs(exp)).padStart(2, "0")}`;
  }
  return String(n);
}

function pyString(s: string): string {
  let out = '"';
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    const ch = s[i];
    if (ch === '"') out += '\\"';
    else if (ch === "\\") out += "\\\\";
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (ch === "\t") out += "\\t";
    else if (ch === "\b") out += "\\b";
    else if (ch === "\f") out += "\\f";
    else if (c < 0x20 || c > 0x7e) out += `\\u${c.toString(16).padStart(4, "0")}`;
    else out += ch;
  }
  return `${out}"`;
}

function pyJson(v: unknown): string {
  if (v === null || v === undefined) return "null";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return pyNumber(v);
  if (typeof v === "string") return pyString(v);
  if (Array.isArray(v)) return `[${v.map(pyJson).join(", ")}]`;
  const o = v as Record<string, unknown>;
  const keys = Object.keys(o).sort();
  return `{${keys.map((k) => `${pyString(k)}: ${pyJson(o[k])}`).join(", ")}}`;
}

/** The renderer's fingerprint of an edit, or null when this browser can't compute it (then nothing is claimed). */
export async function editHash(edit: Record<string, unknown>): Promise<string | null> {
  try {
    if (!crypto?.subtle) return null;
    const data = new TextEncoder().encode(pyJson(edit));
    const buf = await crypto.subtle.digest("SHA-1", data);
    return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 12);
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------ typed times
/** Seconds typed as text: applied on Enter or when leaving the field, so typing never fights the limits. */
export function TimeField({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  const id = useId();
  const [text, setText] = useState(value.toFixed(2));
  useEffect(() => setText(value.toFixed(2)), [value]);
  const commit = () => {
    const n = Number(text.replace(",", "."));
    if (text.trim() !== "" && Number.isFinite(n)) onChange(n);
    else setText(value.toFixed(2));
  };
  return (
    <div className="field time-field">
      <label htmlFor={id}>{label} <span className="faint tnum">{fmtPrecise(value)}</span></label>
      <div className="row">
        <button type="button" className="btn btn-small" aria-label={`${label} 0.5 seconds earlier`}
          onClick={() => onChange(value - 0.5)}>
          −0.5 s
        </button>
        <input id={id} type="text" inputMode="decimal" className="tnum" value={text} aria-describedby={`${id}-u`}
          onChange={(e) => setText(e.target.value)} onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && commit()} />
        <span id={`${id}-u`} className="sr-only">seconds from the start of the source video</span>
        <button type="button" className="btn btn-small" aria-label={`${label} 0.5 seconds later`}
          onClick={() => onChange(value + 0.5)}>
          +0.5 s
        </button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ the timeline
/**
 * The source around the clip: transcript words as marks (a real speech map, not a drawn waveform), the chosen
 * range, the playhead while the source plays, start and end sliders, and the clickable word strip.
 */
export function Timeline({
  lo, hi, start, end, words, playhead, nowWord, clickMode, onClickMode, onTrim, onWord, onReset, canReset,
}: {
  lo: number; hi: number; start: number; end: number; words: Word[]; playhead: number | null; nowWord: number;
  clickMode: "start" | "end"; onClickMode: (m: "start" | "end") => void; onTrim: (s: number, e: number) => void;
  onWord: (w: Word) => void; onReset: () => void; canReset: boolean;
}) {
  const hid = useId();
  const span = Math.max(0.001, hi - lo);
  const pct = (x: number) => `${((100 * (Math.min(hi, Math.max(lo, x)) - lo)) / span).toFixed(3)}%`;
  const shown = words.filter((w) => w.end > lo && w.start < hi);
  return (
    <section className="timeline" aria-labelledby={hid}>
      <div className="panel-head">
        <h2 id={hid} style={{ fontSize: "var(--fs-h3)" }}>Timeline</h2>
        <span className="tiny faint tnum">Source {fmtPrecise(lo)} – {fmtPrecise(hi)}</span>
      </div>
      <div className="tl-track" aria-hidden="true">
        <div className="tl-words">
          {shown.map((w, i) => (
            <i key={i} style={{ left: pct(w.start), width: `max(2px, calc(${pct(w.end)} - ${pct(w.start)}))` }} />
          ))}
        </div>
        <div className="tl-range" style={{ left: pct(start), width: `calc(${pct(end)} - ${pct(start)})` }} />
        {playhead !== null && <div className="tl-head" style={{ left: pct(playhead) }} />}
      </div>
      <div className="tl-ticks" aria-hidden="true">
        <span>{fmtPrecise(lo)}</span><span>{fmtPrecise((lo + hi) / 2)}</span><span>{fmtPrecise(hi)}</span>
      </div>
      <div className="row wrap top">
        <div className="field" style={{ flex: "1 1 180px" }}>
          <label htmlFor={`${hid}-s`}>Start <span className="tnum faint">{fmtPrecise(start)}</span></label>
          <input id={`${hid}-s`} type="range" min={lo} max={Math.max(lo, end - 1)} step={0.1} value={start}
            aria-valuetext={fmtPrecise(start)} onChange={(e) => onTrim(Number(e.target.value), end)} />
        </div>
        <div className="field" style={{ flex: "1 1 180px" }}>
          <label htmlFor={`${hid}-e`}>End <span className="tnum faint">{fmtPrecise(end)}</span></label>
          <input id={`${hid}-e`} type="range" min={Math.min(hi, start + 1)} max={hi} step={0.1} value={end}
            aria-valuetext={fmtPrecise(end)} onChange={(e) => onTrim(start, Number(e.target.value))} />
        </div>
      </div>
      <div className="row wrap">
        <span className="small muted" id={`${hid}-m`}>Click a word to set the</span>
        <Segmented labelledBy={`${hid}-m`} value={clickMode} onChange={onClickMode}
          options={[{ value: "start", label: "start" }, { value: "end", label: "end" }]} />
        <span className="grow" />
        <button type="button" className="btn btn-small btn-quiet" disabled={!canReset} onClick={onReset}>
          Reset to the suggested cut
        </button>
      </div>
      <WordStrip words={shown} start={start} end={end} nowWord={nowWord >= 0 ? shown.indexOf(words[nowWord]) : -1}
        label={`Transcript words. Choose one to set the ${clickMode}.`} onWord={onWord} />
      <p className="tiny faint">
        Cuts snap into the pauses around the words you pick. Use “Source range” above to check a cut before rendering.
      </p>
    </section>
  );
}

/** The words as one toolbar: Tab reaches it once, arrow keys, Home and End move between words. */
function WordStrip({ words, start, end, nowWord, label, onWord }: {
  words: Word[]; start: number; end: number; nowWord: number; label: string; onWord: (w: Word) => void;
}) {
  const inside = (w?: Word) => !!w && w.end > start && w.start < end;
  const first = words.findIndex((w) => inside(w));
  const [focus, setFocus] = useState(-1);
  const current = focus >= 0 && focus < words.length ? focus : Math.max(0, first);
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const key = (e: KeyboardEvent, i: number) => {
    const n = words.length;
    const to = e.key === "ArrowRight" || e.key === "ArrowDown" ? Math.min(n - 1, i + 1)
      : e.key === "ArrowLeft" || e.key === "ArrowUp" ? Math.max(0, i - 1)
        : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
    setFocus(to);
    refs.current[to]?.focus();
  };
  if (!words.length) return <p className="small muted">No transcript words near this clip.</p>;
  return (
    <div className="words" role="toolbar" aria-label={label}>
      {words.map((w, i) => {
        const inn = inside(w);
        const edge = inn && (!inside(words[i - 1]) || !inside(words[i + 1]));
        return (
          <button key={i} ref={(el) => (refs.current[i] = el)} type="button" tabIndex={i === current ? 0 : -1}
            className={`${edge ? "edge" : inn ? "in" : ""} ${i === nowWord ? "now" : ""}`} title={fmtPrecise(w.start)}
            aria-label={`${w.w}, ${fmtPrecise(w.start)}`} onFocus={() => setFocus(i)} onKeyDown={(e) => key(e, i)}
            onClick={() => onWord(w)}>
            {w.w}
          </button>
        );
      })}
    </div>
  );
}
