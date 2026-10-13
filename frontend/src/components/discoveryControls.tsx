import { FormEvent, useEffect, useState } from "react";
import { api, errorText, Settings } from "../api";
import { AutopilotStatus } from "../autopilot";
import { Banner, Icon, toast } from "./ui";
import "./discoveryControls.css";

const limits = {
  discovery_candidates_per_scan: [1, 30], discovery_queue_limit: [1, 100], discovery_creator_limit: [1, 30],
  discovery_min_source_score: [0, 100],
} as const;
type Choice = { discovery_quality_first: boolean; discovery_candidates_per_scan: number;
  discovery_queue_limit: number; discovery_creator_limit: number; discovery_min_source_score: number };
const fromSettings = (s: Settings): Choice => ({
  discovery_quality_first: s.discovery_quality_first !== false,
  discovery_candidates_per_scan: Number(s.discovery_candidates_per_scan ?? 3),
  discovery_queue_limit: Number(s.discovery_queue_limit ?? 6),
  discovery_creator_limit: Number(s.discovery_creator_limit ?? 1),
  discovery_min_source_score: Number(s.discovery_min_source_score ?? 50),
});

export default function DiscoveryControls({ st, refresh }: { st: AutopilotStatus; refresh: () => void }) {
  const [saved, setSaved] = useState<Settings | null>(null);
  const [choice, setChoice] = useState<Choice>(fromSettings({}));
  const [key, setKey] = useState("");
  const [freeOnly, setFreeOnly] = useState(true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    let active = true;
    api.settings().then(s => { if (active) { setSaved(s); setChoice(fromSettings(s)); } })
      .catch(e => { if (active) setProblem(errorText(e)); });
    return () => { active = false; };
  }, []);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    for (const [name, [low, high]] of Object.entries(limits)) {
      const value = choice[name as keyof typeof limits];
      const valid = Number.isFinite(value) && (name === "discovery_min_source_score" || Number.isInteger(value));
      if (!valid || value < low || value > high) {
        setProblem(`Use values within the shown limits; shortlist counts must be whole numbers. ${low}–${high}.`);
        return;
      }
    }
    const patch: Settings = {};
    const before = fromSettings(saved || {});
    for (const field of Object.keys(choice) as (keyof Choice)[]) {
      if (choice[field] !== before[field]) patch[field] = choice[field];
    }
    if (key.trim()) {
      patch.tavily_api_key = key.trim();
      if (freeOnly) { patch.tavily_free_credits = 1000; patch.discovery_monthly_budget_usd = 0; }
    }
    if (!Object.keys(patch).length) { toast("Your discovery choices are already saved"); return; }
    setBusy(true); setProblem("");
    try {
      const result = await api.saveSettings(patch);
      setSaved(result); setChoice(fromSettings(result)); setKey(""); refresh();
      toast("Discovery choices saved for the next search");
    } catch (e) { setProblem(errorText(e)); }
    finally { setBusy(false); }
  };
  const shortlist = st.discovery_shortlist;
  const reasons = shortlist ? Array.isArray(shortlist.reasons) ? shortlist.reasons
    : Object.entries(shortlist.reasons || {}).map(([reason, count]) => ({ reason, count })) : [];
  const use = st.web_search;
  return <section className="panel discovery-controls" aria-labelledby="discovery-quality-title">
    <div className="panel-head"><div>
      <span className="discovery-eyebrow">A smaller, stronger shortlist</span>
      <h2 id="discovery-quality-title">Quality before quantity</h2>
    </div><Icon name="spark" /></div>
    <p className="small muted">Choose a few promising videos and wait when none meets your bar.
      Search scores are estimates; the full video and finished clip are checked afterward.</p>
    {problem && <Banner tone="bad" title="Discovery choices could not be saved">{problem}</Banner>}
    <form onSubmit={save}>
      <label className="discovery-focus"><input type="checkbox" checked={choice.discovery_quality_first}
        disabled={!saved || busy}
        onChange={e => setChoice({ ...choice, discovery_quality_first: e.target.checked })} />
        <span><strong>Use a focused shortlist</strong><small>
          Wait for stronger picks instead of filling the daily target.
          Your chosen folders, channels and links remain available.</small></span></label>
      <div className="discovery-choice-grid">
        <label><span>New finds per search</span><input type="number" min={1} max={30} step={1}
          value={choice.discovery_candidates_per_scan} disabled={!saved || busy}
          onChange={e => setChoice({ ...choice, discovery_candidates_per_scan: Number(e.target.value) })} />
          <small>1–30; 3 is recommended</small></label>
        <label><span>Minimum discovery estimate</span><input type="number" min={0} max={100} step="any"
          value={choice.discovery_min_source_score} disabled={!saved || busy}
          onChange={e => setChoice({ ...choice, discovery_min_source_score: Number(e.target.value) })} />
          <small>0–100; raise it for a stricter search</small></label>
      </div>
      <details className="discovery-details"><summary>Shortlist limits</summary>
        <div className="discovery-choice-grid">
          <label><span>Unfinished finds before waiting</span><input type="number" min={1} max={100} step={1}
            value={choice.discovery_queue_limit} disabled={!saved || busy}
            onChange={e => setChoice({ ...choice, discovery_queue_limit: Number(e.target.value) })} />
            <small>1–100; 6 keeps the backlog small</small></label>
          <label><span>New finds from one creator</span><input type="number" min={1} max={30} step={1}
            value={choice.discovery_creator_limit} disabled={!saved || busy}
            onChange={e => setChoice({ ...choice, discovery_creator_limit: Number(e.target.value) })} />
            <small>1–30 per pass; unknown creators remain unknown</small></label>
        </div>
      </details>
      {shortlist && <div className="discovery-last" aria-label="Last discovery shortlist">
        <strong>Last search pass</strong><p>{shortlist.message}</p>
        <div className="discovery-counts"><span>{shortlist.checked} considered</span>
          <span>{shortlist.admitted} shortlisted</span><span>{shortlist.filtered} filtered</span>
          <span>{shortlist.held} held</span></div>
        {reasons.length > 0 && <details><summary>Why others were left out</summary>
          <ul>{reasons.map(item => <li key={item.reason}>{item.reason} · {item.count}</li>)}</ul>
        </details>}
      </div>}
      <details className="discovery-details discovery-key"><summary>Find better links with a free search key</summary>
        <p>Tavily adds topic-based web search. Its free plan includes 1,000 credits each month, with no credit card.
          This app uses basic searches: one credit per request.</p>
        <ol><li><a className="textlink" href="https://app.tavily.com" target="_blank" rel="noreferrer">
          Open Tavily and create a free account</a>.</li><li>Copy your API key from its dashboard.</li>
          <li>Paste it below and save these choices.</li></ol>
        {saved?.tavily_api_key === "********" && <p className="small">A key is already saved on this PC.</p>}
        <label><span>Tavily API key</span><input type="password" autoComplete="new-password" spellCheck={false}
          maxLength={4096} placeholder="tvly-…" value={key} disabled={!saved || busy}
          onChange={e => setKey(e.target.value)} /><small>
          Leave blank to keep your saved key. Enter it here, not in chat.</small>
        </label>
        <label className="choice small"><input type="checkbox" checked={freeOnly}
          onChange={e => setFreeOnly(e.target.checked)} disabled={busy} />
          Use the free allowance with a $0 app spending limit when saving this key</label>
        {use && <p className="small muted">This app has recorded {use.used} searches in {use.month}.
          The saved allowance is {use.allowed}; your provider dashboard includes usage from other apps too.</p>}
        <p className="small muted">No key is required for your own folders or the free-license library.
          YouTube can also use your connected account or its optional Data API key.
          Search results provide links, not TikTok viewing statistics or reuse permission.</p>
        <a className="textlink small" href="https://www.tavily.com/pricing" target="_blank" rel="noreferrer">
          Current free-plan details</a>
      </details>
      <div className="row wrap discovery-save"><button className="btn btn-primary" disabled={!saved || busy}>
        <Icon name="check" />{busy ? "Saving…" : "Save discovery choices"}</button>
        <span className="small muted">Applies to later searches. Existing videos and jobs are kept.</span></div>
    </form>
  </section>;
}
