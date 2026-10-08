import { FormEvent, useEffect, useMemo, useState } from "react";
import { errorText } from "../api";
import { Banner, EmptyState, Icon, LinkTabs, PageHead, toast } from "../components/ui";
import { brainApi, BrainView, FeedbackClip, ImportIn, ImportResult, Observation } from "../office/api";

/**
 * Clips → Test feedback: what a tester said about a clip, or numbers copied from YouTube Studio / TikTok, entered by
 * hand or imported from a CSV file. Everything is stored with where it came from (self-reported feedback is never
 * mixed up with platform numbers), and a missing number stays missing instead of becoming 0.
 */
export function ClipsTabs({ current }: { current: "clips" | "feedback" }) {
  return <LinkTabs label="Clips sections" current={current} tabs={[
    { id: "clips", href: "#/clips", label: "Videos and clips" },
    { id: "feedback", href: "#/clips/feedback", label: "Test feedback" },
  ]} />;
}

const nowInput = () => {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const NUMBER_FIELDS = ["views", "avg_view_percentage", "avg_view_duration_s", "watch_time_minutes", "likes", "comments",
  "shares", "audience_size"];

export default function Feedback() {
  const [clips, setClips] = useState<FeedbackClip[] | null>(null);
  const [info, setInfo] = useState<BrainView | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    Promise.all([brainApi.feedbackClips(), brainApi.view()]).then(([c, v]) => {
      setClips(c);
      setInfo(v);
    }).catch((e) => setErr(errorText(e)));
  }, []);
  return (
    <div className="page">
      <PageHead title="Test feedback" sub="Tell ClipFoundry how your selected viewers reacted. It learns only from enough real results, and slowly." />
      <ClipsTabs current="feedback" />
      {err && <Banner tone="bad" title="Could not load">{err}</Banner>}
      {clips && info && (clips.length ? (
        <div className="feedback-grid">
          <FeedbackForm clips={clips} info={info} />
          <CsvImport info={info} />
        </div>
      ) : (
        <EmptyState icon="film" title="No clips yet">Make a clip first. Feedback is always about one clip.</EmptyState>
      ))}
    </div>
  );
}

function FeedbackForm({ clips, info }: { clips: FeedbackClip[]; info: BrainView }) {
  const [clip, setClip] = useState(clips[0].clip_id + "|" + clips[0].platform);
  const [kind, setKind] = useState<"tester_feedback" | "owner_import">("tester_feedback");
  const [tester, setTester] = useState("");
  const [ratings, setRatings] = useState<Record<string, string>>({});
  const [numbers, setNumbers] = useState<Record<string, string>>({});
  const [stopped, setStopped] = useState("");
  const [note, setNote] = useState("");
  const [at, setAt] = useState(nowInput());
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [history, setHistory] = useState<Observation[] | null>(null);
  const [clipId, platform] = clip.split("|");
  const chosen = clips.find((c) => c.clip_id === clipId && c.platform === platform);

  useEffect(() => {
    let alive = true;
    brainApi.clip(clipId).then((r) => alive && setHistory(r.observations)).catch(() => alive && setHistory([]));
    return () => {
      alive = false;
    };
  }, [clipId]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setProblem("");
    const values: Record<string, unknown> = {};
    if (kind === "tester_feedback") {
      for (const [k, v] of Object.entries(ratings)) if (v) values[k] = Number(v);
      if (stopped.trim()) values.stopped_at_s = stopped.trim();
    } else {
      for (const [k, v] of Object.entries(numbers)) if (v.trim()) values[k] = v.trim();
    }
    if (!Object.keys(values).length) {
      setProblem(kind === "tester_feedback" ? "Choose at least one answer." : "Enter at least one number.");
      return;
    }
    if (kind === "tester_feedback" && !tester.trim()) {
      setProblem("Add a label for the tester (a first name or initials is enough), so two testers are counted as two.");
      return;
    }
    setBusy(true);
    try {
      const r = await brainApi.add({ clip_id: clipId, platform, provenance: kind, values,
        observed_at: at ? new Date(at).getTime() / 1000 : null, tester: tester.trim(), note: note.trim() });
      toast({ added: "Saved", duplicate: "Already saved before: nothing changed", corrected: "Saved as a correction" }[r.status] || "Saved");
      setRatings({});
      setNumbers({});
      setStopped("");
      setNote("");
      brainApi.clip(clipId).then((x) => setHistory(x.observations)).catch(() => {});
    } catch (e2) {
      setProblem(errorText(e2));
    }
    setBusy(false);
  };

  return (
    <form className="card feedback-form" onSubmit={submit}>
      <h2>Add feedback for one clip</h2>
      <label className="field">
        <span>Clip</span>
        <select value={clip} onChange={(e) => setClip(e.target.value)}>
          {clips.map((c) => (
            <option key={c.clip_id + c.platform} value={c.clip_id + "|" + c.platform}>
              {c.title}{c.platform ? ` · ${c.platform === "youtube" ? "YouTube" : "TikTok"}` : " · not posted"}
            </option>
          ))}
        </select>
        {chosen && <span className="hint">Audience: {chosen.cohort_label}{chosen.cohort !== "selected" ? ". Results from this audience are kept apart and never change a strategy." : "."}</span>}
      </label>
      <fieldset className="field">
        <legend>What are you entering?</legend>
        <label className="check-inline"><input type="radio" name="kind" checked={kind === "tester_feedback"} onChange={() => setKind("tester_feedback")} /> What a tester told me</label>
        <label className="check-inline"><input type="radio" name="kind" checked={kind === "owner_import"} onChange={() => setKind("owner_import")} disabled={!platform} /> Numbers from {platform === "tiktok" ? "TikTok" : "YouTube Studio"}{!platform && " (only for posted clips)"}</label>
      </fieldset>
      {kind === "tester_feedback" ? (<>
        <label className="field"><span>Tester</span>
          <input value={tester} onChange={(e) => setTester(e.target.value)} maxLength={60} placeholder="First name or initials" />
          <span className="hint">Only a label. No email or account is needed.</span></label>
        {Object.entries(info.fields.ratings).map(([k, label]) => (
          <fieldset key={k} className="field rating">
            <legend>{label}</legend>
            <div className="seg">
              {[1, 2, 3, 4, 5].map((n) => (
                <label key={n} className={ratings[k] === String(n) ? "on" : ""}>
                  <input type="radio" name={`r-${k}`} value={n} checked={ratings[k] === String(n)}
                    onChange={() => setRatings({ ...ratings, [k]: String(n) })} />{n}
                </label>
              ))}
            </div>
          </fieldset>
        ))}
        <p className="hint">1 = not at all, 5 = completely. Skip what the tester did not answer.</p>
        <label className="field"><span>Stopped watching at (seconds, optional)</span>
          <input inputMode="decimal" value={stopped} onChange={(e) => setStopped(e.target.value)} /></label>
      </>) : (
        <div className="field-grid">
          {NUMBER_FIELDS.map((k) => (
            <label key={k} className="field"><span>{info.fields.metrics[k]?.label || k}{info.fields.metrics[k]?.unit === "%" ? " (%)" : ""}</span>
              <input inputMode="decimal" value={numbers[k] || ""} onChange={(e) => setNumbers({ ...numbers, [k]: e.target.value })} /></label>
          ))}
          <p className="hint">Leave a box empty when you do not have that number. Empty is not 0.</p>
        </div>
      )}
      <label className="field"><span>When was this true?</span>
        <input type="datetime-local" value={at} max={nowInput()} onChange={(e) => setAt(e.target.value)} /></label>
      <label className="field"><span>Note (optional)</span>
        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} /></label>
      {problem && <p className="error-text" role="alert"><Icon name="alert" className="sm" />{problem}</p>}
      <button type="submit" className="btn btn-primary" disabled={busy}><Icon name="check" />Save feedback</button>
      <h3>Saved for this clip</h3>
      {history === null ? <p className="muted small">Loading…</p> : history.length ? (
        <ul className="op-list">
          {history.slice(0, 8).map((o) => (
            <li key={o.id}>
              <span className="pill">{info.fields.provenance[o.provenance]}</span>
              <span className="grow small">{Object.entries(o.metrics).filter(([, v]) => v !== null).map(([k, v]) =>
                `${info.fields.metrics[k]?.label || info.fields.ratings[k] || k}: ${v}`).join(" · ")}
                {o.tester ? ` (${o.tester})` : ""}{o.revision > 1 ? " · corrected" : ""}</span>
              <span className="muted tiny nowrap">{new Date(o.observed_at * 1000).toLocaleDateString()}</span>
            </li>
          ))}
        </ul>
      ) : <p className="muted small">Nothing saved for this clip yet.</p>}
    </form>
  );
}

function CsvImport({ info }: { info: BrainView }) {
  const [file, setFile] = useState<{ name: string; text: string } | null>(null);
  const [kind, setKind] = useState<"owner_import" | "tester_feedback">("owner_import");
  const [platform, setPlatform] = useState("");
  const [date, setDate] = useState("");
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [done, setDone] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const body = useMemo((): ImportIn | null => file ? { text: file.text, provenance: kind, platform,
    observed_at: date ? new Date(date).getTime() / 1000 : null, filename: file.name } : null, [file, kind, platform, date]);

  useEffect(() => {
    setPreview(null);
    setDone(null);
  }, [body]);

  const pick = async (f: File | undefined) => {
    setProblem("");
    if (!f) return;
    if (f.size > 5 * 1024 * 1024) {
      setProblem("That file is larger than 5 MB. Export fewer rows.");
      return;
    }
    setFile({ name: f.name, text: await f.text() });
  };
  const run = async (save: boolean) => {
    if (!body) return;
    setBusy(true);
    setProblem("");
    try {
      if (save) {
        setDone(await brainApi.importCsv(body));
        toast("Import finished");
      } else setPreview(await brainApi.preview(body));
    } catch (e) {
      setProblem(errorText(e));
    }
    setBusy(false);
  };
  const shown = done || preview;
  const usable = (preview?.counts.new || 0) + (preview?.counts.correction || 0);
  return (
    <section className="card">
      <h2>Import a CSV file</h2>
      <p className="small muted">A YouTube Studio export (Advanced mode → Export → .csv), or your own file with a clip column. Importing the same file twice adds nothing.</p>
      <label className="field"><span>File</span><input type="file" accept=".csv,text/csv" onChange={(e) => pick(e.target.files?.[0])} /></label>
      <fieldset className="field">
        <legend>The file holds</legend>
        <label className="check-inline"><input type="radio" name="csvkind" checked={kind === "owner_import"} onChange={() => setKind("owner_import")} /> Platform numbers I exported</label>
        <label className="check-inline"><input type="radio" name="csvkind" checked={kind === "tester_feedback"} onChange={() => setKind("tester_feedback")} /> Testers' answers</label>
      </fieldset>
      <div className="field-grid">
        <label className="field"><span>Platform</span>
          <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
            <option value="">From the file</option><option value="youtube">YouTube</option><option value="tiktok">TikTok</option>
          </select></label>
        <label className="field"><span>Date of the export</span>
          <input type="datetime-local" value={date} max={nowInput()} onChange={(e) => setDate(e.target.value)} />
          <span className="hint">Used for rows without their own date.</span></label>
      </div>
      {problem && <p className="error-text" role="alert"><Icon name="alert" className="sm" />{problem}</p>}
      <div className="row wrap">
        <button type="button" className="btn" disabled={!body || busy} onClick={() => run(false)}><Icon name="question" />Check the file</button>
        <button type="button" className="btn btn-primary" disabled={!preview || !usable || busy || !!done} onClick={() => run(true)}>
          <Icon name="upload" />Import {usable || ""} row{usable === 1 ? "" : "s"}</button>
      </div>
      {shown && (<>
        <p className="small">{Object.entries(shown.counts).map(([k, n]) => `${n} ${k}`).join(" · ") || "No rows"}
          {preview?.columns && preview.columns.ignored.length > 0 && <span className="muted"> · columns not used: {preview.columns.ignored.join(", ")}</span>}</p>
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Row</th><th>Clip</th><th>Result</th></tr></thead>
            <tbody>{shown.rows.slice(0, 50).map((r) => (
              <tr key={r.line}><td>{r.line}</td><td>{r.clip_title || r.clip_id || "—"}{r.cohort_label ? <span className="block muted tiny">{r.cohort_label}</span> : null}</td>
                <td><span className={`pill ${r.status === "error" ? "bad" : r.status === "duplicate" ? "" : "good"}`}>{r.status}</span> <span className="small">{r.message}</span></td></tr>
            ))}</tbody>
          </table>
        </div>
      </>)}
      <p className="hint">Metrics it understands: {Object.values(info.fields.metrics).map((m) => m.label).join(", ")}.</p>
    </section>
  );
}
