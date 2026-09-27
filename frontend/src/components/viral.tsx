import type { Clip, QualityReport } from "../api";
import { fmtTime } from "../api";

export const FACTOR_LABELS: [string, string][] = [
  ["hook", "Hook strength"], ["opening", "Opening strength"], ["curiosity", "Curiosity"],
  ["emotion", "Emotional intensity"], ["density", "Information density"], ["payoff", "Story / payoff"],
  ["standalone", "Standalone context"], ["pacing", "Pacing"], ["uniqueness", "Uniqueness"],
  ["clarity", "Speaker clarity"], ["retention", "Retention potential"],
];

const SUBSCORES: [keyof NonNullable<Clip["analysis"]["subscores"]>, string][] = [
  ["hook", "Hook Score"], ["retention", "Retention Potential"], ["context", "Context Score"],
  ["engagement", "Engagement Potential"],
];

// Clips scored before Viral Potential existed keep their five original criteria.
const LEGACY: [string, string][] = [
  ["hook", "Hook"], ["engagement", "Engagement"], ["context", "Context"], ["payoff", "Payoff"], ["standalone", "Standalone"],
];

export const ESTIMATE_NOTE = "Estimates from the clip's transcript and audio, used to rank clips. Not a guarantee of views.";

const tone = (v: number, max: number) => (v / max >= 0.7 ? "hi" : v / max >= 0.5 ? "mid" : "lo");

/** Four sub-scores as compact "Hook 81 · Retention 80 ..." text for cards. */
export function SubscoreLine({ c }: { c: Clip }) {
  const sub = c.analysis?.subscores;
  if (!sub) return null;
  return (
    <div className="subline" title={ESTIMATE_NOTE}>
      {SUBSCORES.map(([k, label]) => (
        <span key={k} className={tone(sub[k], 100)}>{label.split(" ")[0]} {sub[k]}</span>
      ))}
    </div>
  );
}

export function StructureChips({ c }: { c: Clip }) {
  const st = c.analysis?.structure;
  if (!st) return null;
  if (!st.hook && !st.context && !st.payoff) return <div className="structure"><span className="off">{st.label}</span></div>;
  return (
    <div className="structure" title="Short-form clips work best when they open with a hook, give just enough context and end on the payoff.">
      {(["hook", "context", "payoff"] as const).map((k, i) => (
        <span key={k} style={{ display: "contents" }}>
          {i > 0 && <i>→</i>}
          <span className={st[k] ? "on" : "off"}>{st[k] ? "✓" : "✗"} {k[0].toUpperCase() + k.slice(1)}</span>
        </span>
      ))}
    </div>
  );
}

/** Full breakdown: sub-scores, structure, the eleven factors and anything to watch out for. */
export function ViralPanel({ c }: { c: Clip }) {
  const a = c.analysis || {};
  if (!a.subscores) {
    return (
      <div className="scorebars">
        {LEGACY.map(([k, label]) => (
          <div className="scorebar" key={k}>
            <span>{label}</span>
            <div className="bar"><div style={{ width: `${(c.scores?.[k] ?? 0) * 10}%` }} /></div>
            <span>{(c.scores?.[k] ?? 0).toFixed(1)}</span>
          </div>
        ))}
        <div className="small muted">Scored by an older version. Regenerate the project for the Viral Potential breakdown.</div>
      </div>
    );
  }
  return (
    <div className="viral">
      <div className="subscores">
        {SUBSCORES.map(([k, label]) => (
          <div key={k} className={`subscore ${tone(a.subscores![k], 100)}`}>
            <b>{a.subscores![k]}</b>
            <span>{label}</span>
          </div>
        ))}
      </div>
      <StructureChips c={c} />
      {(a.flags || []).length > 0 && (
        <ul className="flags">
          {a.flags!.map((f) => (
            <li key={f.id} className={f.severity}><b>{f.label}:</b> {f.detail}</li>
          ))}
        </ul>
      )}
      <details>
        <summary className="small">All 11 factors</summary>
        <div className="scorebars mt-s">
          {FACTOR_LABELS.map(([k, label]) => (
            <div className="scorebar wide" key={k}>
              <span>{label}</span>
              <div className="bar"><div style={{ width: `${(a.factors?.[k] ?? 0) * 10}%` }} /></div>
              <span>{(a.factors?.[k] ?? 0).toFixed(1)}</span>
            </div>
          ))}
        </div>
      </details>
      <div className="small muted">{a.note || ESTIMATE_NOTE}</div>
    </div>
  );
}

/** Why fewer clips than requested (or none) are shown. */
export function QualitySummary({ q, clipCount }: { q: QualityReport; clipCount: number }) {
  const counts = Object.entries(q.reject_counts || {}).sort((a, b) => b[1] - a[1]);
  const left = q.evaluated - clipCount;
  return (
    <div className={`notice ${clipCount ? "" : "warn"} block mt`}>
      <b>{clipCount ? `${clipCount} clip${clipCount === 1 ? "" : "s"} passed the quality bar` : "No clip passed the quality bar"}</b>
      {" "}({q.requested} requested, {q.evaluated} candidates evaluated, minimum Viral Potential {q.min_score}).
      {" "}Only strong moments are kept; weaker filler is never added to reach the count.
      {left > 0 && counts.length > 0 && (
        <details className="mt-s">
          <summary>Why {left} candidate{left === 1 ? " was" : "s were"} left out</summary>
          <div className="row wrap mt-s" style={{ gap: 6 }}>
            {counts.map(([k, n]) => <span key={k} className="badge">{k} × {n}</span>)}
          </div>
          <ul className="rejected">
            {q.rejected.map((r, i) => (
              <li key={i}>
                <span className="muted">{fmtTime(r.start)}-{fmtTime(r.end)} · {Math.round(r.score)}</span>{" "}
                “{r.text.length > 110 ? r.text.slice(0, 110) + "..." : r.text}”
                <div className="small">{r.reasons.join(" · ")}</div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
