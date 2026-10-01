import { useId, useState } from "react";
import { api, errorText, PerfSnapshot, Publication } from "../api";
import { Icon, toast } from "./ui";

const NOT_REPORTED = "Not reported by the platform (ClipFoundry never estimates a missing number)";

export const fmtNum = (n: number | null | undefined) =>
  n === null || n === undefined ? "—"
    : n >= 10000 ? `${(n / 1000).toFixed(n >= 100000 ? 0 : 1)}k` : n.toLocaleString();

const fmtDuration = (s: number | null) =>
  s === null ? "—" : s >= 60 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${s.toFixed(1)}s`;

/** Real numbers from the platform; "—" (with the reason on hover and for screen readers) where it reports none. */
export function StatsGrid({ s }: { s: PerfSnapshot }) {
  const cells: [string, string, boolean][] = [
    ["Views", fmtNum(s.views), s.views === null],
    ["Likes", fmtNum(s.likes), s.likes === null],
    ["Comments", fmtNum(s.comments), s.comments === null],
    ["Shares", fmtNum(s.shares), s.shares === null],
    ["Watch time", s.watch_time_minutes === null ? "—" : `${fmtNum(Math.round(s.watch_time_minutes))} min`,
      s.watch_time_minutes === null],
    ["Avg. view", fmtDuration(s.avg_view_duration_s), s.avg_view_duration_s === null],
    ["Avg. % viewed", s.avg_view_percentage === null ? "—" : `${s.avg_view_percentage.toFixed(0)}%`,
      s.avg_view_percentage === null],
  ];
  return (
    <div className="stats">
      <div className="stat-grid">
        {cells.map(([k, v, missing]) => (
          <div key={k} className={missing ? "missing" : ""}
            title={missing ? NOT_REPORTED : `${k}, as reported by the platform`}>
            <b>{v}{missing && <span className="sr-only"> (not available: {NOT_REPORTED})</span>}</b><span>{k}</span>
          </div>
        ))}
      </div>
      <span className="tiny faint">As of {new Date(s.fetched_at * 1000).toLocaleString()} · {s.source}</span>
      {s.notes.map((n, i) => <span key={i} className="tiny faint">{n}</span>)}
    </div>
  );
}

/** Real numbers for one upload: refresh them, and (TikTok) link the real post after finishing it in the app. */
export function PublicationStats({ p, onChange }: { p: Publication; onChange: (p: Publication) => void }) {
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState("");
  const id = useId();
  if (!["done", "action_needed"].includes(p.status)) return null;
  const run = async (fn: () => Promise<Publication>) => {
    setBusy(true);
    try {
      onChange(await fn());
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setBusy(false);
    }
  };
  const needsLink = p.platform === "tiktok" && !(p.info?.post_ids || []).length;
  return (
    <div className="pub-stats">
      <div className="row wrap">
        <b className="small grow">Real numbers</b>
        <button type="button" className="btn btn-small btn-quiet" disabled={busy}
          onClick={() => run(() => api.refreshStats(p.id))}>
          {busy ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="refresh" />}
          {p.stats ? "Refresh numbers" : "Get numbers"}
        </button>
      </div>
      {p.stats ? <StatsGrid s={p.stats} /> : <span className="small muted">No numbers read yet.</span>}
      {needsLink && (
        <div className="field">
          <label htmlFor={id} className="small">Posted it in the TikTok app? Paste its link to read its numbers</label>
          <div className="row">
            <input id={id} type="url" inputMode="url" placeholder="https://www.tiktok.com/@you/video/…" value={link}
              onChange={(e) => setLink(e.target.value)} />
            <button type="button" className="btn btn-small" disabled={!link.trim() || busy}
              onClick={() => run(() => api.linkTikTok(p.id, link.trim()))}>Link</button>
          </div>
        </div>
      )}
    </div>
  );
}
