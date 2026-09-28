import { useState } from "react";
import { api, errorText, PerfSnapshot, Publication } from "../api";
import { Icon, toast } from "./ui";

const NOT_REPORTED = "Not reported by the platform's API (ClipFoundry never estimates missing numbers)";

export const fmtNum = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : n >= 10000 ? `${(n / 1000).toFixed(n >= 100000 ? 0 : 1)}k` : n.toLocaleString();

const fmtDuration = (s: number | null) => (s === null ? "—" : s >= 60 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${s.toFixed(1)}s`);

/** Real numbers from the platform API; "—" where the platform does not report a metric. */
export function StatsGrid({ s }: { s: PerfSnapshot }) {
  const cells: [string, string, boolean][] = [
    ["Views", fmtNum(s.views), s.views === null],
    ["Likes", fmtNum(s.likes), s.likes === null],
    ["Comments", fmtNum(s.comments), s.comments === null],
    ["Shares", fmtNum(s.shares), s.shares === null],
    ["Watch time", s.watch_time_minutes === null ? "—" : `${fmtNum(Math.round(s.watch_time_minutes))} min`, s.watch_time_minutes === null],
    ["Avg. view", fmtDuration(s.avg_view_duration_s), s.avg_view_duration_s === null],
    ["Avg. % viewed", s.avg_view_percentage === null ? "—" : `${s.avg_view_percentage.toFixed(0)}%`, s.avg_view_percentage === null],
  ];
  return (
    <div className="stats">
      <div className="stat-grid">
        {cells.map(([k, v, missing]) => (
          <div key={k} className={missing ? "missing" : ""} title={missing ? NOT_REPORTED : `${k}, as reported by the platform`}>
            <b>{v}</b><span>{k}</span>
          </div>
        ))}
      </div>
      <div className="small muted">As of {new Date(s.fetched_at * 1000).toLocaleString()} · {s.source}</div>
      {s.notes.map((n, i) => <div key={i} className="small muted">{n}</div>)}
    </div>
  );
}

/** Stats block for one upload: refresh, and (TikTok) link the real post after finishing it in the app. */
export function PublicationStats({ p, onChange }: { p: Publication; onChange: (p: Publication) => void }) {
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState("");
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
      <div className="row between">
        <b className="small">Real performance</b>
        <button className="btn sm ghost" disabled={busy} onClick={() => run(() => api.refreshStats(p.id))}>
          <Icon name="refresh" size={12} /> {p.stats ? "Refresh stats" : "Get stats"}
        </button>
      </div>
      {p.stats ? <StatsGrid s={p.stats} /> : <div className="small muted">No statistics fetched yet.</div>}
      {needsLink && (
        <div className="row mt-s">
          <input type="text" placeholder="Posted it in the TikTok app? Paste the video link to track it" value={link} onChange={(e) => setLink(e.target.value)} />
          <button className="btn sm" disabled={!link.trim() || busy} onClick={() => run(() => api.linkTikTok(p.id, link.trim()))}>Link</button>
        </div>
      )}
    </div>
  );
}
