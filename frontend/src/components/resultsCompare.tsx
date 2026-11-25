import { useEffect, useState } from "react";
import { api, CompareBy, CompareGroup, CompareResult, errorText } from "../api";
import { num, plural } from "../format";
import { Icon, PlatformName, Segmented, Skel } from "./ui";

const BY: { value: CompareBy; label: string }[] = [
  { value: "format", label: "Format" }, { value: "channel", label: "Channel" }, { value: "niche", label: "Niche" },
  { value: "length", label: "Clip length" },
];

const VERDICT: Record<CompareGroup["verdict"], { label: string; tone: string; icon: "graph" | "info" | "clock" }> = {
  higher: { label: "Higher so far", tone: "good", icon: "graph" },
  lower: { label: "Lower so far", tone: "warn", icon: "graph" },
  inconclusive: { label: "No clear difference yet", tone: "neutral", icon: "info" },
  too_few: { label: "Too few posts", tone: "neutral", icon: "clock" },
  only_one: { label: "Nothing to compare", tone: "neutral", icon: "info" },
};

function views(v: number | null) {
  return v === null ? "—" : num(Math.round(v));
}

/** The verdict's sentence without the words its pill already says ("Higher so far: a median of…"). */
function detail(g: CompareGroup) {
  const label = VERDICT[g.verdict].label;
  if (!g.text.startsWith(`${label}: `)) return g.text;
  const rest = g.text.slice(label.length + 2);
  return rest.charAt(0).toUpperCase() + rest.slice(1);
}

/**
 * Posts → Results → Compare: your posts grouped by format, channel, niche or clip length, each group against the
 * rest of the same platform and audience, every post read 48 hours after your viewers could first watch it. A
 * difference is "clear" only with enough posts on both sides and a gap unlikely by chance; otherwise it says so.
 * Each row ends with a test you can run next. What happened, never a promise of views.
 */
export function ResultsCompare() {
  const [by, setBy] = useState<CompareBy>("format");
  const [res, setRes] = useState<CompareResult | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    setError("");
    api.compareResults(by).then((r) => live && setRes(r)).catch((e) => live && setError(errorText(e)));
    return () => { live = false; };
  }, [by]);
  return (
    <section className="compare" aria-labelledby="cmp-h">
      <div className="row wrap compare-head">
        <div className="stack" style={{ gap: 2 }}>
          <h3 id="cmp-h">Compare</h3>
          <p className="small muted">
            Each group against your other posts on the same platform and audience, every post read 48 hours after it
            went out.
          </p>
        </div>
        <Segmented value={by} options={BY} onChange={setBy} label="Compare by" />
      </div>
      {error ? <p className="small" role="alert">{error}</p>
        : !res || res.by !== by ? <div aria-busy="true"><Skel className="skel-line" /></div>
          : res.places.length === 0 ? (
            <p className="small muted">
              Nothing to compare yet: a post counts 48 hours after your viewers could first watch it, once its numbers
              are read (Refresh numbers).
            </p>
          ) : (
            <>
              {res.places.map((pl) => (
                <div className="compare-place" key={`${pl.platform}:${pl.cohort}`}>
                  <h4 className="row wrap" style={{ gap: 6 }}>
                    <PlatformName platform={pl.platform} />
                    <span className="small muted">· {pl.audience} · {plural(pl.posts, "post")}</span>
                  </h4>
                  {!pl.available ? (
                    <p className="small">
                      <span className="pill neutral"><Icon name="info" />Not used</span> {pl.note}
                    </p>
                  ) : (
                    <>
                      <div className="table-wrap">
                        <table className="data">
                          <caption className="sr-only">
                            {`${res.label} on ${pl.platform === "youtube" ? "YouTube" : "TikTok"}, ${pl.audience}`}
                          </caption>
                          <thead>
                            <tr>
                              <th scope="col">{res.label}</th><th scope="col" className="num">Posts</th>
                              <th scope="col" className="num">Median views at 48 h</th>
                              {pl.groups.some((g) => g.pct_reported)
                                && <th scope="col" className="num">Median % viewed</th>}
                              <th scope="col">So far</th><th scope="col">Test next</th>
                            </tr>
                          </thead>
                          <tbody>
                            {pl.groups.map((g) => {
                              const v = VERDICT[g.verdict];
                              return (
                                <tr key={g.group}>
                                  <th scope="row">{g.group}</th>
                                  <td className="num">{g.posts}</td>
                                  <td className="num">{views(g.median_views)}</td>
                                  {pl.groups.some((x) => x.pct_reported) && (
                                    <td className="num">
                                      {g.median_pct === null
                                        ? <span className="metric-missing" title="Not reported by the platform">—</span>
                                        : `${Math.round(g.median_pct)}%`}
                                    </td>
                                  )}
                                  <td>
                                    <span className={`pill ${v.tone}`}><Icon name={v.icon} />{v.label}</span>
                                    <div className="tiny muted">{detail(g)}</div>
                                  </td>
                                  <td className="small">{g.test}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                      {pl.periods && (
                        <p className="small muted">
                          <Icon name="calendar" /> Last {pl.periods.days} days:{" "}
                          {plural(pl.periods.recent.posts, "post")}, median {views(pl.periods.recent.median_views)}{" "}
                          views. The {pl.periods.days} days before:{" "}
                          {plural(pl.periods.before.posts, "post")}, median{" "}
                          {views(pl.periods.before.median_views)}.{" "}
                          {pl.periods.text}
                        </p>
                      )}
                      {!!pl.note && <p className="tiny faint">{pl.note}</p>}
                    </>
                  )}
                </div>
              ))}
              <p className="tiny faint">
                {res.note} A difference counts as clear with at least {res.min_posts} posts on each side and a gap
                unlikely to be chance.
              </p>
            </>
          )}
    </section>
  );
}
