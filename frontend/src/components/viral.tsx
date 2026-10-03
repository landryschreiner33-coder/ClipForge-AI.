import type { Clip, QualityReport } from "../api";
import { fmtTime } from "../api";
import { plural } from "../format";
import { Disclosure, Icon } from "./ui";

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
  ["hook", "Hook"], ["engagement", "Engagement"], ["context", "Context"], ["payoff", "Payoff"],
  ["standalone", "Standalone"],
];

export const ESTIMATE_NOTE =
  "Estimates from the clip's transcript and audio, used to rank clips. Not a guarantee of views.";

// The number is always shown; the color only repeats it (strong, middling, weak).
const tone = (v: number, max: number) => (v / max >= 0.7 ? "hi" : v / max >= 0.5 ? "mid" : "lo");

/** Four sub-scores as compact "Hook 81 · Retention 80 ..." text for cards (all estimates). */
export function SubscoreLine({ c }: { c: Clip }) {
  const sub = c.analysis?.subscores;
  if (!sub) return null;
  return (
    <div className="subline" title={ESTIMATE_NOTE}>
      {SUBSCORES.map(([k, label]) => (
        <span key={k} className={tone(sub[k], 100)}>{label.split(" ")[0]} {sub[k]}</span>
      ))}
      <span className="sr-only">(estimates)</span>
    </div>
  );
}

/** Hook → Context → Payoff, each with an icon and a word (never color alone). */
export function StructureChips({ c }: { c: Clip }) {
  const st = c.analysis?.structure;
  if (!st) return null;
  if (!st.hook && !st.context && !st.payoff) {
    return <div className="structure"><span className="off">{st.label}</span></div>;
  }
  return (
    <div className="structure"
      title="Short clips work best when they open with a hook, give just enough context and end on the payoff.">
      {(["hook", "context", "payoff"] as const).map((k, i) => (
        <span key={k} style={{ display: "contents" }}>
          {i > 0 && <i aria-hidden="true">→</i>}
          <span className={`row ${st[k] ? "on" : "off"}`} style={{ gap: 4 }}>
            <Icon name={st[k] ? "check" : "x"} className="xs" />
            {k[0].toUpperCase() + k.slice(1)}
            <span className="sr-only">{st[k] ? " found" : " missing"}</span>
          </span>
        </span>
      ))}
    </div>
  );
}

/** Full breakdown: sub-scores, structure, the eleven factors and anything to watch out for. All estimates. */
export function ViralPanel({ c }: { c: Clip }) {
  const a = c.analysis || {};
  if (!a.subscores) {
    return (
      <div className="scorebars">
        {LEGACY.map(([k, label]) => (
          <div className="scorebar" key={k}>
            <span>{label}</span>
            <div className="bar" aria-hidden="true"><div style={{ width: `${(c.scores?.[k] ?? 0) * 10}%` }} /></div>
            <span className="tnum">{(c.scores?.[k] ?? 0).toFixed(1)}</span>
          </div>
        ))}
        <p className="tiny faint">
          Scored by an older version (estimates). Make clips again for the Viral Potential breakdown.
        </p>
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
            <li key={f.id} className={f.severity}>
              <b>{f.severity === "block" ? "Problem" : "Watch out"}: {f.label}.</b> {f.detail}
            </li>
          ))}
        </ul>
      )}
      <Disclosure plain summary="All 11 factors">
        <div className="scorebars">
          {FACTOR_LABELS.map(([k, label]) => (
            <div className="scorebar wide" key={k}>
              <span>{label}</span>
              <div className="bar" aria-hidden="true"><div style={{ width: `${(a.factors?.[k] ?? 0) * 10}%` }} /></div>
              <span className="tnum">{(a.factors?.[k] ?? 0).toFixed(1)}</span>
            </div>
          ))}
        </div>
      </Disclosure>
      <p className="tiny faint">{a.note || ESTIMATE_NOTE}</p>
    </div>
  );
}

/**
 * Why fewer clips than asked for (or none) were made: "3 of 11 moments passed the quality bar", and what kept
 * the others out. Weak moments are never added to reach the count.
 */
export function QualitySummary({ q, clipCount }: { q: QualityReport; clipCount: number }) {
  const counts = Object.entries(q.reject_counts || {}).sort((a, b) => b[1] - a[1]);
  const left = q.evaluated - clipCount;
  const passed = clipCount
    ? `${clipCount} of ${plural(q.evaluated, "moment")} passed the quality bar`
    : `None of the ${plural(q.evaluated, "moment")} passed the quality bar`;
  return (
    <div className="stack">
      <p className="small">
        {passed} ({q.requested} asked for, minimum Viral Potential {q.min_score}, an estimate). Weak moments are never
        added to
        reach the count.
      </p>
      {left > 0 && counts.length > 0 && (
        <Disclosure plain summary={`Why ${plural(left, "moment was", "moments were")} left out`}>
          <div className="row wrap" style={{ gap: 6 }}>
            {counts.map(([k, n]) => <span key={k} className="tag">{k} × {n}</span>)}
          </div>
          <ul className="rejected">
            {q.rejected.map((r, i) => (
              <li key={i}>
                <span className="faint tnum">
                  {fmtTime(r.start)}–{fmtTime(r.end)} · estimate {Math.round(r.score)}
                </span>{" "}
                “{r.text.length > 110 ? `${r.text.slice(0, 110)}…` : r.text}”
                <div className="tiny muted">{r.reasons.join(" · ")}</div>
              </li>
            ))}
          </ul>
        </Disclosure>
      )}
    </div>
  );
}
