/** The viral predictor's panel: the score, the hook, how long people stay (the hold curve), a per-second heatmap of
 * five channels, the reasons and the fixes. Every number is an estimate (predictor.ts). */
import { useEffect, useId, useMemo, useState } from "react";
import { errorText } from "../api";
import {
  CHANNEL_LABELS, clock, ClipPrediction, Prediction, PredictorAccuracy, PredictorFix, PREDICTOR_NOTE, predictor,
  watchedWords,
} from "../predictor";
import { Disclosure, Icon } from "./ui";
import "./predictor.css";

const tone = (v: number) => (v >= 75 ? "hi" : v >= 50 ? "mid" : "lo");

/** The score in a ring, with its band in words (never color alone). */
export function ScoreRing({ score, band, size = 76 }: { score: number; band: string; size?: number }) {
  const r = 32;
  const c = 2 * Math.PI * r;
  return (
    <div className={`vp-ring ${tone(score)}`} style={{ width: size, height: size }}>
      <svg viewBox="0 0 80 80" aria-hidden="true">
        <circle cx="40" cy="40" r={r} className="vp-track" />
        <circle cx="40" cy="40" r={r} className="vp-value" strokeDasharray={`${(c * score) / 100} ${c}`}
          transform="rotate(-90 40 40)" />
      </svg>
      <span className="vp-ring-num"><b className="tnum">{score}</b><small>{band}</small></span>
    </div>
  );
}

/** A small "Viral 72 · Good" line for clip cards. */
export function PredictorBadge({ p }: { p: { score: number; band: string; avg_view: number | null; fixes: number } | null | undefined }) {
  if (!p) return null;
  return (
    <span className={`vp-badge ${tone(p.score)}`} title={PREDICTOR_NOTE}>
      <span className="vp-badge-main"><Icon name="graph" className="xs" /><b className="tnum">{p.score}</b> Viral score · {p.band}
        <span className="sr-only"> (estimate)</span></span>
      {(p.avg_view != null || p.fixes > 0) && <span className="tiny faint">
        {[p.avg_view != null ? `${p.avg_view}% watched` : "", p.fixes > 0 ? `${p.fixes} fix${p.fixes === 1 ? "" : "es"}` : ""]
          .filter(Boolean).join(" · ")}
      </span>}
    </span>
  );
}

/** Who is still watching, second by second (the modelled audience), with the peak and the biggest drops. */
function HoldCurve({ p, onSeek }: { p: Prediction; onSeek?: (t: number) => void }) {
  const W = 320;
  const Hh = 96;
  const curve = p.hold.curve;
  const last = Math.max(1, curve.length - 1);
  const x = (t: number) => (Math.min(t, p.duration) / Math.max(p.duration, last)) * W;
  const y = (v: number) => Hh - v * (Hh - 8) - 4;
  const path = curve.map((v, i) => `${i ? "L" : "M"}${x(Math.min(i, p.duration)).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const label = `Hold curve: ${watchedWords(p)}. Strongest moment at ${clock(p.peak.t)}.` +
    (p.hold.drops.length ? ` Viewers leave fastest around ${p.hold.drops.map((d) => clock(d.t)).join(", ")}.` : "");
  return (
    <figure className="vp-curve">
      <svg viewBox={`0 0 ${W} ${Hh}`} role="img" aria-label={label}
        onClick={onSeek ? (e) => {
          const box = e.currentTarget.getBoundingClientRect();
          onSeek(((e.clientX - box.left) / box.width) * Math.max(p.duration, last));
        } : undefined}>
        {[0.25, 0.5, 0.75].map((g) => <line key={g} x1="0" x2={W} y1={y(g)} y2={y(g)} className="vp-grid" />)}
        <path d={`${path} L${x(Math.min(last, p.duration)).toFixed(1)},${Hh} L0,${Hh} Z`} className="vp-area" />
        <path d={path} className="vp-line" />
        <line x1={x(p.peak.t)} x2={x(p.peak.t)} y1="0" y2={Hh} className="vp-peak" />
        {p.hold.drops.map((d) => (
          <circle key={d.t} cx={x(d.t)} cy={y(curve[Math.min(curve.length - 1, Math.round(d.t))] ?? 0)} r="3.5" className="vp-drop" />
        ))}
      </svg>
      <figcaption className="tiny faint">
        Still watching, second by second (modelled audience). <span className="vp-key vp-key-peak" /> strongest moment
        {p.hold.drops.length > 0 && <> · <span className="vp-key vp-key-drop" /> where most leave</>}
        {onSeek && " · click to jump there"}
      </figcaption>
    </figure>
  );
}

/** At most this many cells a row: a longer video's seconds are grouped (each cell is a few seconds). */
const HEAT_CELLS = 120;

/** Five channels, one cell per second (or per few seconds for a long video); a stronger cell means the viewer gets
 * more from that channel then. */
function Heatmap({ p, onSeek }: { p: Prediction; onSeek?: (t: number) => void }) {
  const secs = p.channels.vision.length;
  const step = Math.max(1, Math.ceil(secs / HEAT_CELLS));
  const cells = Math.ceil(secs / step);
  const rows = useMemo(() => CHANNEL_LABELS.map(([k]) => {
    const v = p.channels[k];
    return Array.from({ length: cells }, (_, i) => {
      const part = v.slice(i * step, (i + 1) * step);
      return part.reduce((a, b) => a + b, 0) / Math.max(1, part.length);
    });
  }), [p, step, cells]);
  const summary = useMemo(() => CHANNEL_LABELS.map(([k, label]) => {
    const v = p.channels[k];
    const mean = v.reduce((a, b) => a + b, 0) / Math.max(1, v.length);
    const best = v.indexOf(Math.max(...v));
    return `${label}: ${Math.round(mean * 100)}% on average, strongest at ${clock(best)}`;
  }).join(". "), [p]);
  const when = (i: number) => step === 1 ? clock(i) : `${clock(i * step)}–${clock(Math.min(secs, (i + 1) * step))}`;
  return (
    <figure className="vp-heat">
      <div className="vp-heat-grid" role="img" aria-label={`Heatmap. ${summary}.`}
        style={{ gridTemplateColumns: `6.5em repeat(${cells}, minmax(3px, 1fr))` }}>
        {CHANNEL_LABELS.map(([k, label, help], row) => (
          <div key={k} className="vp-heat-row" style={{ display: "contents" }}>
            <span className="vp-heat-label tiny" title={help}>{label}</span>
            {rows[row].map((v, i) => (
              <span key={i} className={`vp-cell ${k}`} style={{ opacity: 0.12 + 0.88 * Math.max(0, Math.min(1, v)) }}
                title={`${label} at ${when(i)}: ${Math.round(v * 100)}%`}
                onClick={onSeek ? () => onSeek(i * step) : undefined} />
            ))}
          </div>
        ))}
      </div>
      <figcaption className="tiny faint">
        {!p.measured.picture && "The picture is measured once the clip is rendered. "}
        {!p.measured.words && "No words were heard. "}
        Stronger means more for the viewer {step === 1 ? "in that second" : `in those ${step} seconds`}
        {onSeek ? `; click ${step === 1 ? "a second" : "a cell"} to jump there` : ""}.
      </figcaption>
    </figure>
  );
}

function gainWords(g: NonNullable<PredictorFix["gain"]>): string {
  const parts = [];
  if (g.score) parts.push(`${g.score > 0 ? "+" : ""}${g.score} score`);
  if (g.avg_view) parts.push(`${g.avg_view > 0 ? "+" : ""}${g.avg_view}% watched`);
  if (g.hook) parts.push(`${g.hook > 0 ? "+" : ""}${g.hook} hook`);
  return parts.join(" · ");
}

export function FixList({ fixes, onApply, onSeek, applyLabel = "Apply", busy, appliedIds }: {
  fixes: PredictorFix[]; onApply?: (f: PredictorFix) => void; onSeek?: (t: number) => void; applyLabel?: string;
  busy?: boolean; appliedIds?: string[];
}) {
  if (!fixes.length) {
    return <p className="small muted">No change tried on this clip helped enough to suggest it.</p>;
  }
  return (
    <ol className="vp-fixes">
      {fixes.map((f) => (
        <li key={f.id}>
          <div className="grow">
            <b>{f.label}</b>
            <p className="small muted">{f.why}</p>
            {f.gain && <span className="tiny vp-gain">Tried on the clip: {gainWords(f.gain) || "keeps more viewers"}</span>}
            {f.at != null && onSeek && f.at > 0 && (
              <button type="button" className="textlink tiny vp-jump" onClick={() => onSeek(f.at!)}>Play from {clock(f.at)}</button>
            )}
          </div>
          {f.kind === "edit" && onApply ? (
            <button type="button" className="btn btn-small" disabled={busy || appliedIds?.includes(f.id)}
              onClick={() => onApply(f)}>
              {appliedIds?.includes(f.id) ? <><Icon name="check" />Added</> : applyLabel}
            </button>
          ) : <span className="tiny faint">Advice</span>}
        </li>
      ))}
    </ol>
  );
}

/** The whole prediction. `onApply` puts a fix's change into the clip's edit; `onSeek` jumps the player. */
export function PredictorPanel({ p, onSeek, onApply, applyLabel, busy, appliedIds, headingLevel = 3 }: {
  p: Prediction; onSeek?: (t: number) => void; onApply?: (f: PredictorFix) => void; applyLabel?: string;
  busy?: boolean; appliedIds?: string[]; headingLevel?: 2 | 3;
}) {
  const hid = useId();
  const Hd = headingLevel === 2 ? "h2" : "h3";
  const avg = p.hold.avg_view_calibrated ?? p.hold.avg_view;
  return (
    <section className="vp-panel" aria-labelledby={hid}>
      <div className="vp-head">
        <ScoreRing score={p.score} band={p.band} />
        <div className="grow">
          <Hd id={hid}>Viral score {p.score} <span className="faint">· {p.band}</span></Hd>
          <p className="tiny faint">{p.note || PREDICTOR_NOTE}</p>
        </div>
      </div>
      <dl className="vp-stats">
        <div><dt>Hook</dt><dd className={tone(p.hook.score)}><b className="tnum">{p.hook.score}</b>/100</dd></div>
        <div><dt>Watched</dt><dd><b className="tnum">{avg}%</b> on average</dd></div>
        <div><dt>To the end</dt><dd><b className="tnum">{p.hold.rate}%</b></dd></div>
        <div><dt>Strongest moment</dt><dd>
          {onSeek ? <button type="button" className="textlink" onClick={() => onSeek(p.peak.t)}>{clock(p.peak.t)}</button>
            : clock(p.peak.t)}
        </dd></div>
      </dl>
      {p.hold.calibrated_on != null && (
        <p className="tiny faint">Average watched calibrated on {p.hold.calibrated_on} of your posts.</p>
      )}
      <HoldCurve p={p} onSeek={onSeek} />
      <Heatmap p={p} onSeek={onSeek} />
      <h4 className="vp-sub">What to fix</h4>
      <FixList fixes={p.fixes} onApply={onApply} onSeek={onSeek} applyLabel={applyLabel} busy={busy} appliedIds={appliedIds} />
      <h4 className="vp-sub">Why</h4>
      <ul className="vp-reasons">
        {p.reasons.map((r, i) => (
          <li key={i} className={r.good === true ? "good" : r.good === false ? "weak" : "unknown"}>
            <Icon name={r.good === true ? "check" : r.good === false ? "alert" : "info"} className="xs" />
            <span><b>{r.area}:</b> {r.text}
              {r.t != null && r.t > 0 && onSeek && (
                <> <button type="button" className="textlink tiny" onClick={() => onSeek(r.t!)}>{clock(r.t)}</button></>
              )}
            </span>
          </li>
        ))}
      </ul>
      {p.words_note && <p className="tiny faint">{p.words_note}</p>}
    </section>
  );
}

/** The clip editor's and Prepare post's card: the prediction of the file shown (the clip or one version), with
 * Predict for a clip rendered before the predictor existed. */
export function ClipPredictorCard({ clipId, versionId = "", stamp, busy, onSeek, onApply, applyLabel, appliedIds, open = true,
  editorHref }: {
  /** versionId: the file shown ("" is the clip itself, never "whichever version is posted"). */
  clipId: string; versionId?: string; stamp: string; busy?: boolean; onSeek?: (t: number) => void;
  onApply?: (f: PredictorFix) => void; applyLabel?: string; appliedIds?: string[]; open?: boolean;
  /** Prepare post: where the fixes can be made, with a note that says how. */
  editorHref?: string;
}) {
  const [state, setState] = useState<ClipPrediction | null>(null);
  const [problem, setProblem] = useState("");
  const [working, setWorking] = useState(false);
  useEffect(() => {
    let alive = true;
    setProblem("");
    predictor.ofClip(clipId, versionId).then((s) => alive && setState(s))
      .catch((e) => alive && setProblem(errorText(e)));
    return () => {
      alive = false;
    };
  }, [clipId, versionId, stamp]);
  const run = async () => {
    setWorking(true);
    setProblem("");
    try {
      const r = await predictor.predictClip(clipId, versionId);
      setState((s) => ({ enabled: s?.enabled ?? true, rendered: true, prediction: r.prediction }));
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setWorking(false);
    }
  };
  const p = state?.prediction;
  return (
    <Disclosure open={open} summary={<span className="row" style={{ gap: 6 }}><Icon name="graph" />Viral predictor
      {p && <span className="faint small"> · {p.score} {p.band}</span>}</span>}>
      <div className="stack-2">
        {busy ? <p className="small muted">The new video is predicted when the render finishes.</p>
          : p ? (
            <>
              <PredictorPanel p={p} onSeek={onSeek} onApply={onApply} applyLabel={applyLabel} appliedIds={appliedIds} />
              {editorHref && p.fixes.length > 0 && (
                <p className="tiny faint">
                  {p.fixes.some((f) => f.kind === "edit")
                    ? <>Want to use a fix? <a className="textlink" href={editorHref}>Open the editor</a>, add it with one
                      press, then render.</>
                    : <>These fixes are advice for this version: make the change in <a className="textlink"
                      href={editorHref}>the editor</a>, then render.</>}
                </p>
              )}
            </>
          )
            : state && !state.enabled ? (
              <p className="small muted">The viral predictor is off. Turn it on in <a className="textlink" href="#/settings/ai">Settings → ClipForge AI</a>.</p>
            ) : state && !state.rendered ? <p className="small muted">Render the clip to predict how it will do.</p>
              : state ? (
                <div className="stack-2">
                  <p className="small muted">This video was made before the predictor, or changed since. Predicting takes a few seconds.</p>
                  <button type="button" className="btn btn-small" disabled={working} onClick={run}>
                    {working && <span className="inline-spinner" aria-hidden="true" />}<Icon name="graph" />Predict how it will do
                  </button>
                </div>
              ) : !problem && <p className="small muted">Loading…</p>}
        {problem && <p className="small error-text">{problem}</p>}
      </div>
    </Disclosure>
  );
}

/** How well the viral predictor matched your real results (shown with Results). */
export function PredictorAccuracyPanel() {
  const [acc, setAcc] = useState<PredictorAccuracy | null>(null);
  useEffect(() => {
    predictor.accuracy().then(setAcc).catch(() => setAcc(null));
  }, []);
  if (!acc) return null;
  const rows = Object.entries(acc.platforms);
  const name = (p: string) => (p === "youtube" ? "YouTube" : p === "tiktok" ? "TikTok" : p);
  return (
    <section className="stack-2" aria-labelledby="vp-acc">
      <h3 id="vp-acc" className="row" style={{ gap: 6 }}><Icon name="graph" />Viral predictor vs. real results</h3>
      {rows.length === 0 ? (
        <p className="small muted">
          Each post keeps what the predictor said when it went out. Once {acc.min_posts} posts on a platform have their
          results (48 hours after they go out), this shows how well it matched, and it starts calibrating itself.
        </p>
      ) : (
        <div className="table-wrap">
          <table className="vp-acc-table">
            <thead><tr><th>Platform</th><th>Posts</th><th>Rank match</th><th>Top third beat the median</th><th>Average watched off by</th></tr></thead>
            <tbody>
              {rows.map(([p, a]) => (
                <tr key={p}>
                  <td>{name(p)}</td>
                  <td className="tnum">{a.posts}</td>
                  <td className="tnum">{a.spearman === null ? <span className="faint">needs {acc.min_posts}</span> : a.spearman.toFixed(2)}</td>
                  <td className="tnum">{a.top_third_hit === null ? <span className="faint">—</span> : `${Math.round(a.top_third_hit * 100)}%`}</td>
                  <td className="tnum">{a.avg_view_error === null ? <span className="faint">—</span> : `${a.avg_view_error} points (${a.avg_view_posts} posts)`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.map(([p, a]) => a.bands.length > 1 && (
        <p key={p} className="tiny faint">
          {name(p)} median views by predicted band: {a.bands.map((b) => `${b.band} ${Math.round(b.median_views)}`
            + (b.vs_median ? ` (${b.vs_median}× your median)` : "")).join(" · ")}.
        </p>
      ))}
      <p className="tiny faint">
        Rank match: 1 means the predicted order was the real order of views, 0 means no relation.
        {acc.paused ? " Learning is paused with the Brain: predictions use the designed values until you turn it back on."
          : <>
            {acc.learned?.hold ? ` Average watched is calibrated on ${acc.learned.hold.n} of your posts.` : ` Average watched is calibrated after ${acc.min_calibration} posts report it.`}
            {acc.learned?.weights ? ` The score's parts are weighted by what worked for you (${acc.learned.n} posts, each moved at most 10% per update, and only after 10 new posts).`
              : ` The score's parts start re-weighting after ${acc.min_weights} posts.`}
          </>}
      </p>
    </section>
  );
}
