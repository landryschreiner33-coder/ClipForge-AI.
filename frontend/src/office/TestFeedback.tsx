import { FormEvent, useEffect, useId, useState } from "react";
import { errorText } from "../api";
import { Icon, Pill, Segmented, toast } from "../components/ui";
import { ClipFeedback, CsvPreview, office } from "./officeApi";

/**
 * Test feedback for one clip: what the Brain has for it, and two small forms. "Numbers I read on the platform" are
 * the owner's import; "What a tester told me" is self-reported. Nothing is estimated: an empty box is not sent.
 */
type Mode = "owner_import" | "tester_feedback";
const NUMBERS: [string, string, string][] = [
  ["views", "Views", "count"], ["avg_view_percentage", "Average % viewed", "percent"], ["likes", "Likes", "count"],
  ["comments", "Comments", "count"], ["shares", "Shares", "count"],
];
const RATINGS: [string, string][] = [
  ["hook", "Hook"], ["context", "Context"], ["payoff", "Payoff"], ["captions", "Captions"], ["overall", "Overall"],
];
const numOrNull = (s: string) => (s.trim() === "" ? null : Number(s));

export function TestFeedback({ clipId }: { clipId: string }) {
  const [fb, setFb] = useState<ClipFeedback | null>(null);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<Mode>("owner_import");
  const [platform, setPlatform] = useState<"youtube" | "tiktok">("youtube");
  const [nums, setNums] = useState<Record<string, string>>({});
  const [sample, setSample] = useState("");
  const [rates, setRates] = useState<Record<string, string>>({});
  const [comment, setComment] = useState("");
  const [stopped, setStopped] = useState("");
  const [tester, setTester] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const id = useId();
  const load = () => office.clipFeedback(clipId).then((v) => { setFb(v); setError(""); })
    .catch((e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, [clipId]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setFormError("");
    const body: Record<string, unknown> = { clip_id: clipId, platform, provenance: mode, comment };
    if (mode === "owner_import") {
      const metrics = Object.fromEntries(NUMBERS.map(([k]) => [k, numOrNull(nums[k] || "")]));
      if (Object.values(metrics).some((v) => v !== null && (Number.isNaN(v) || v < 0))) {
        setFormError("Numbers must be 0 or more.");
        return;
      }
      if (metrics.avg_view_percentage !== null && metrics.avg_view_percentage > 100) {
        setFormError("Average % viewed is at most 100.");
        return;
      }
      body.metrics = metrics;
      const n = numOrNull(sample);
      if (n !== null) body.sample_size = Math.round(n);
    } else {
      body.ratings = Object.fromEntries(RATINGS.map(([k]) => [k, numOrNull(rates[k] || "")]));
      body.stopped_at_s = numOrNull(stopped);
      body.tester_id = tester.trim();
    }
    setBusy(true);
    try {
      const out = await office.feedback(body);
      toast(out.duplicates && !out.stored ? "Already recorded: nothing new was added"
        : `Saved ${out.stored} ${out.stored === 1 ? "entry" : "entries"}`);
      setNums({});
      setSample("");
      setRates({});
      setComment("");
      setStopped("");
      load();
    } catch (err) {
      setFormError(errorText(err));
    }
    setBusy(false);
  };

  return (
    <section className="panel tight test-feedback" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`} style={{ fontSize: "var(--fs-h3)" }}>Test feedback</h2>
      <p className="tiny faint">What your selected viewers did or said. This is test-audience evidence, not proof of how
        the wider public would respond, and it stays on this PC.</p>
      {error ? <p className="small bad-text">{error}</p> : !fb ? <p className="small muted">Waiting for data.</p> : (
        <div className="stack">
          <div className="row wrap"><Pill tone="neutral" icon="info">{fb.state}</Pill>
            <span className="small">{fb.next}</span></div>
          <p className="small">
            {fb.observations ? `${fb.observations} recorded: ` : "Nothing recorded yet."}
            {fb.observations > 0 && Object.entries(fb.by_provenance).filter(([, n]) => n > 0)
              .map(([k, n]) => `${fb.labels[k] || k}: ${n}`).join(" · ")}
          </p>
        </div>
      )}
      <form className="stack-3" onSubmit={submit} aria-describedby={formError ? `${id}-err` : undefined}>
        <Segmented<Mode> label="Kind of feedback" value={mode} onChange={setMode} options={[
          { value: "owner_import", label: "Numbers I read on the platform" },
          { value: "tester_feedback", label: "What a tester told me" },
        ]} />
        <Segmented<"youtube" | "tiktok"> label="Platform" value={platform} onChange={setPlatform} options={[
          { value: "youtube", label: "YouTube" }, { value: "tiktok", label: "TikTok" },
        ]} />
        {mode === "owner_import" ? (
          <div className="fb-grid">
            {NUMBERS.map(([k, label]) => (
              <div className="field" key={k}>
                <label htmlFor={`${id}-${k}`}>{label}</label>
                <input id={`${id}-${k}`} type="number" min={0} max={k === "avg_view_percentage" ? 100 : undefined}
                  step={k === "avg_view_percentage" ? "0.1" : "1"} inputMode="decimal" value={nums[k] || ""}
                  onChange={(e) => setNums((n) => ({ ...n, [k]: e.target.value }))} />
              </div>
            ))}
            <div className="field">
              <label htmlFor={`${id}-sample`}>Audience size <span className="hint">people who could watch</span></label>
              <input id={`${id}-sample`} type="number" min={0} step="1" value={sample}
                onChange={(e) => setSample(e.target.value)} />
            </div>
          </div>
        ) : (
          <>
            <p className="tiny muted"><b>Self-reported:</b> what one tester told you. Ratings are 1 (poor) to 5
              (great); leave any you don't know empty.</p>
            <div className="fb-grid">
              {RATINGS.map(([k, label]) => (
                <div className="field" key={k}>
                  <label htmlFor={`${id}-r-${k}`}>{label}</label>
                  <select id={`${id}-r-${k}`} value={rates[k] || ""}
                    onChange={(e) => setRates((r) => ({ ...r, [k]: e.target.value }))}>
                    <option value="">—</option>
                    {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                </div>
              ))}
              <div className="field">
                <label htmlFor={`${id}-stop`}>Where they stopped <span className="hint">seconds</span></label>
                <input id={`${id}-stop`} type="number" min={0} step="0.5" value={stopped}
                  onChange={(e) => setStopped(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor={`${id}-tester`}>Tester label <span className="hint">optional, e.g. T1</span></label>
                <input id={`${id}-tester`} type="text" maxLength={40} value={tester}
                  onChange={(e) => setTester(e.target.value)} />
              </div>
            </div>
          </>
        )}
        <div className="field">
          <label htmlFor={`${id}-comment`}>{mode === "owner_import" ? "Note (optional)" : "What they said"}</label>
          <textarea id={`${id}-comment`} rows={2} maxLength={1000} value={comment}
            onChange={(e) => setComment(e.target.value)} />
        </div>
        {formError && <p id={`${id}-err`} className="small bad-text" role="alert">{formError}</p>}
        <div className="row wrap">
          <button type="submit" className="btn btn-primary btn-small" disabled={busy}>
            {busy && <span className="inline-spinner" aria-hidden="true" />}Save feedback
          </button>
        </div>
      </form>
    </section>
  );
}

/** Paste or choose a CSV, Preview it (every problem by line), then Import. Nothing is stored before Import. */
export function CsvImport({ onDone }: { onDone?: () => void }) {
  const [text, setText] = useState("");
  const [filename, setFilename] = useState("");
  const [preview, setPreview] = useState<CsvPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const id = useId();
  const reset = (t: string, name = "") => {
    setText(t);
    setFilename(name);
    setPreview(null);
    setError("");
  };
  const run = async (commit: boolean) => {
    setBusy(true);
    setError("");
    try {
      if (commit) {
        const out = await office.importCommit(text, filename);
        toast(`Imported ${out.stored} ${out.stored === 1 ? "number" : "numbers"}`
          + (out.duplicates ? ` (${out.duplicates} already there)` : ""));
        reset("");
        onDone?.();
      } else {
        setPreview(await office.importPreview(text, filename));
      }
    } catch (e) {
      setError(errorText(e));
    }
    setBusy(false);
  };
  return (
    <div className="stack-3 csv-import">
      <p className="tiny muted">Columns: <code>clip_id</code> (or <code>platform_video_id</code>),
        {" "}<code>platform</code>,
        <code>observed_at</code> (when you read the numbers), then either <code>metric</code> and <code>value</code>, or
        one column per number (<code>views</code>, <code>avg_view_percentage</code>, <code>likes</code>…).</p>
      <div className="field">
        <label htmlFor={`${id}-file`}>Choose a CSV file</label>
        <input id={`${id}-file`} type="file" accept=".csv,text/csv" onChange={(e) => {
          const f = e.target.files?.[0];
          if (!f) return;
          f.text().then((t) => reset(t, f.name)).catch(() => setError("That file could not be read."));
        }} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-text`}>Or paste it here</label>
        <textarea id={`${id}-text`} rows={4} value={text} spellCheck={false} className="mono"
          onChange={(e) => reset(e.target.value, filename)} />
      </div>
      <div className="row wrap">
        <button type="button" className="btn btn-small" disabled={!text.trim() || busy} onClick={() => run(false)}>
          Preview</button>
        <button type="button" className="btn btn-small btn-primary"
          disabled={!preview || preview.rejected > 0 || preview.accepted === 0 || busy} onClick={() => run(true)}>
          Import</button>
      </div>
      {error && <p className="small bad-text" role="alert">{error}</p>}
      {preview && (
        <div className="stack" role="status">
          <p className="small"><Icon name={preview.rejected ? "alert" : "check"} className="sm" /> {preview.accepted}
            {" "}row{preview.accepted === 1 ? "" : "s"} ready, {preview.rejected} with problems
            {preview.columns.length ? ` · columns: ${preview.columns.join(", ")}` : ""}.</p>
          {preview.problems.length > 0 && (
            <ul className="csv-problems">
              {preview.problems.slice(0, 50).map((p, i) => (
                <li key={i} className="small"><b>Line {p.line}:</b> {p.problem}</li>
              ))}
            </ul>
          )}
          {preview.rejected > 0 && <p className="tiny muted">Fix these lines and preview again; nothing is imported
            while any line has a problem.</p>}
        </div>
      )}
    </div>
  );
}
