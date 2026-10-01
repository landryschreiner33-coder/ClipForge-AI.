import { useEffect, useState } from "react";
import { api, errorText, PerformanceOverview, PerfSnapshot } from "../api";
import { num, plural, when } from "../format";
import { EmptyState, Icon, PlatformName, Skel, toast } from "./ui";
import { Post } from "./postShared";

// /api/performance also says why YouTube numbers are left out of the totals (publish/routes.py).
type Overview = PerformanceOverview & { totals_note?: string; excluded_from_totals?: number };
type Item = Overview["items"][number];

const METRICS: { key: "views" | "likes" | "comments" | "shares"; label: string }[] = [
  { key: "views", label: "Views" }, { key: "likes", label: "Likes" }, { key: "comments", label: "Comments" },
  { key: "shares", label: "Shares" },
];

/** Why a number is "—": nothing was read yet, or the platform does not report it. Never estimated. */
function missingWhy(i: Item): string {
  const name = i.platform === "youtube" ? "YouTube" : "TikTok";
  if (!i.stats) return `No numbers read from ${name} yet. Press Refresh numbers.`;
  const notes = i.stats.notes.join(" ");
  return `Not reported by ${name}${notes ? `: ${notes}` : "."}`;
}

function Cell({ v, i, suffix = "" }: { v: number | null | undefined; i: Item; suffix?: string }) {
  if (v === null || v === undefined) {
    const why = missingWhy(i);
    return (
      <td className="num">
        <span className="metric-missing" tabIndex={0} title={why} aria-label={`Not available: ${why}`}>—</span>
      </td>
    );
  }
  return <td className="num">{num(Math.round(v * 10) / 10)}{suffix}</td>;
}

/**
 * Posts → Results: real numbers read from YouTube and TikTok for your own posts. A number a platform doesn't report
 * is "—" with the reason; nothing is estimated. Viral Potential at posting is ClipFoundry's estimate, labeled as
 * such.
 */
export function PostResults({ posts }: { posts: Post[] }) {
  const [perf, setPerf] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.performance().then((p) => setPerf(p as Overview)).catch((e) => setError(errorText(e)));
  }, []);
  const refresh = async () => {
    setBusy(true);
    try {
      const r = await api.refreshAllStats();
      setPerf((await api.performance()) as Overview);
      if (r.failed.length) {
        const why = `${r.failed.length} could not be read: ${r.failed[0].error}`;
        toast(`Updated ${plural(r.refreshed, "post")}; ${why}`, true);
      }
      else toast(`Updated the numbers of ${plural(r.refreshed, "post")}`);
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setBusy(false);
    }
  };
  if (error) return <EmptyState icon="alert" title="Results could not be loaded">{error}</EmptyState>;
  if (!perf) {
    return <div className="panel" aria-busy="true"><Skel className="skel-line" /><Skel className="skel-block" /></div>;
  }

  // A result row opens its post when Autopilot planned it, or the clip's Prepare post page for an upload you started.
  const postOf = new Map(posts.filter((p) => p.publication?.id).map((p) => [p.publication!.id, p.id]));
  const t = perf.totals;
  const check = perf.check;
  return (
    <section className="panel" aria-labelledby="res-h">
      <div className="panel-head">
        <div className="stack" style={{ gap: 2 }}>
          <h2 id="res-h">Results</h2>
          <p className="small muted">
            Real numbers read from YouTube and TikTok for your own posts. A number a platform doesn't report is shown as
            “—”, never estimated.
          </p>
        </div>
        <div className="row wrap">
          {perf.last_refreshed && <span className="tiny faint">Updated {when(perf.last_refreshed)}</span>}
          <button type="button" className="btn btn-small" disabled={busy || !perf.published} onClick={refresh}>
            {busy ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="refresh" />}Refresh numbers
          </button>
          <a className="btn btn-small btn-quiet" href="/api/performance/dataset" download
            title="Each post's scores at posting next to its real numbers, for your own analysis">
            <Icon name="download" />Download data (CSV)
          </a>
        </div>
      </div>
      {perf.published === 0 ? (
        <p className="muted">Nothing published yet. Numbers appear here after your first post goes out.</p>
      ) : (
        <>
          <div className="totals">
            {METRICS.map((m) => {
              const tot = t[m.key];
              const missing = !tot || tot.total === null;
              return (
                <div className="total" key={m.key}>
                  <b>{missing ? "—" : num(Math.round(tot.total as number))}</b>
                  <span>
                    {m.label}
                    {missing ? " · not reported yet" : tot.publications < perf.published
                      ? ` · from ${tot.publications} of ${plural(perf.published, "post")}` : ""}
                  </span>
                </div>
              );
            })}
          </div>
          {!!perf.totals_note && (
            <p className="small">
              <span className="pill neutral"><Icon name="info" />YouTube</span> {perf.totals_note}
            </p>
          )}
          <div className="table-wrap">
            <table className="data">
              <caption className="sr-only">Results per post</caption>
              <thead>
                <tr>
                  <th scope="col">Post</th><th scope="col">Platform</th>
                  {METRICS.map((m) => <th scope="col" className="num" key={m.key}>{m.label}</th>)}
                  <th scope="col" className="num">Avg. % viewed</th>
                  <th scope="col" className="num">Viral Potential at posting</th>
                </tr>
              </thead>
              <tbody>
                {perf.items.map((i) => {
                  const s = (i.stats || {}) as Partial<PerfSnapshot>;
                  const postId = postOf.get(i.id);
                  return (
                    <tr key={i.id}>
                      <td>
                        <a className="textlink" href={postId ? `#/post/${postId}` : `#/publish/${i.clip_id}`}>
                          {i.title || "Untitled post"}
                        </a>
                        <div className="tiny faint">Posted {when(i.created_at)}</div>
                      </td>
                      <td><PlatformName platform={i.platform} /></td>
                      <Cell v={s.views} i={i} /><Cell v={s.likes} i={i} />
                      <Cell v={s.comments} i={i} /><Cell v={s.shares} i={i} />
                      <Cell v={s.avg_view_percentage} i={i} suffix="%" />
                      <td className="num">
                        {i.viral_potential === null ? <span className="faint">—</span>
                          : <>{Math.round(i.viral_potential)} <span className="tiny faint">(estimate)</span></>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {perf.items.length < perf.published && (
            <p className="tiny faint">
              The table shows the newest {perf.items.length} of {plural(perf.published, "post")}; the totals count all
              of them.
            </p>
          )}
          <p className="small muted">
            {check.spearman === null
              ? `Comparing Viral Potential with real views needs at least ${check.min_samples} posts with view counts `
                + `(now ${check.samples}).`
              : `Viral Potential vs. real views over ${plural(check.samples, "post")}: rank correlation `
                + `${check.spearman.toFixed(2)} (1 = the same order, 0 = no relation).`}
          </p>
        </>
      )}
    </section>
  );
}
