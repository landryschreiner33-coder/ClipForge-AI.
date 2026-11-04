import { useCallback, useEffect, useState } from "react";
import { errorText } from "../api";
import { fmtTime, Snapshot, Story, studio } from "../studio";
import { UsedFromBrain } from "./studioParts";
import { Banner, Icon, Pill, toast } from "./ui";

const WORDS = { complete: ["good", "Complete"], uncertain: ["warn", "Check the boundaries"], incomplete: ["bad", "May be cut off"] } as const;

/** Full stories review: chronological story cards and the gaps between them, with simple boundary controls and one
 * batch action. Confident stories are already being made; uncertain ones wait here. */
export default function StoryReview({ projectId, version, onChange }: { projectId: string; version: number; onChange: () => void }) {
  const [stories, setStories] = useState<Story[] | null>(null);
  const [summary, setSummary] = useState<Record<string, any>>({});
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => studio.stories(projectId).then((r) => { setStories(r.stories); setSummary(r.summary || {}); })
    .catch(() => setStories([])), [projectId]);
  useEffect(() => {
    void load();  // again whenever the project changes (it is polled while the server works on it)
  }, [load, version]);
  useEffect(() => {
    studio.projectGuidance(projectId).then((g) => setSnap(g.snapshot)).catch(() => setSnap(null));
  }, [projectId]);
  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try {
      await fn();
      toast(done);
      await load();
      onChange();
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
  };
  if (stories === null) return <p className="muted">Loading stories…</p>;
  const held = stories.filter((s) => s.kind === "story" && !s.clip_id && s.included);
  return (
    <section className="panel" aria-labelledby="stories-title">
      <div className="panel-head">
        <h2 id="stories-title">Stories</h2>
        {held.length > 0 && <button type="button" className="btn btn-primary" disabled={busy}
          onClick={() => act(() => studio.createStoryClips(projectId, held.map((s) => s.id)), `${held.length} story clip${held.length > 1 ? "s" : ""} started`)}>
          <Icon name="film" />Make {held.length} more clip{held.length > 1 ? "s" : ""}</button>}
      </div>
      <p className="small muted">{summary.method ? `Boundaries are a ${summary.method}; check them before posting.` : ""}
        {summary.note ? ` ${summary.note}` : ""}</p>
      {snap && <details><summary>Used from your Brain</summary><UsedFromBrain snapshot={snap} compact /></details>}
      {stories.length === 0 && <Banner tone="info" title="No stories yet">They appear here once the video has been read.</Banner>}
      <div className="story-cards">
        {stories.map((s, i) => s.kind === "gap" ? (
          <div key={s.id} className="story-card gap">
            <span className="small"><b>{s.title}</b> · {fmtTime(s.start)}–{fmtTime(s.end)} · not a story</span>
          </div>
        ) : (
          <article key={s.id} className={`story-card ${s.included ? "" : "excluded"}`}>
            <div className="row">
              <h3>{s.title || `Story ${i + 1}`}</h3>
              <Pill tone={WORDS[s.completeness][0]} icon={s.completeness === "complete" ? "check" : "alert"}>{WORDS[s.completeness][1]}</Pill>
              <span className="times">{fmtTime(s.start)}–{fmtTime(s.end)} · {fmtTime(s.duration)}</span>
            </div>
            <p className="quote">Starts “{s.opening}” · ends “{s.closing}”</p>
            <p className="small muted">{s.reason}</p>
            {s.eligibility.length > 0 && <ul className="small">{s.eligibility.map((e) => (
              <li key={e.connection_id}><b>{e.account}</b>: {e.text}{e.alternatives ? ` Options: ${e.alternatives.join("; ")}.` : ""}</li>))}</ul>}
            <div className="row">
              {s.clip_id ? <a className="btn btn-small" href={`#/clip/${s.clip_id}`}><Icon name="edit" />Open clip ({s.clip_status})</a>
                : s.included && <button type="button" className="btn btn-small" disabled={busy}
                  onClick={() => act(() => studio.createStoryClips(projectId, [s.id]), "Clip started")}>{s.completeness === "complete" ? "Make this clip" : "Looks right, make it"}</button>}
              <button type="button" className="btn btn-small" disabled={busy} onClick={() => act(() => studio.patchStory(s.id, { included: !s.included }), s.included ? "Left out" : "Included")}>
                {s.included ? "Leave out" : "Include"}</button>
              <button type="button" className="btn btn-small" disabled={busy} onClick={() => act(() => studio.patchStory(s.id, { start: Math.max(0, s.start - 2) }), "Starts 2 s earlier")}>Start 2 s earlier</button>
              <button type="button" className="btn btn-small" disabled={busy} onClick={() => act(() => studio.patchStory(s.id, { end: s.end + 2 }), "Ends 2 s later")}>End 2 s later</button>
              <button type="button" className="btn btn-small" disabled={busy || s.duration < 10} onClick={() => act(() => studio.splitStory(projectId, s.id, (s.start + s.end) / 2), "Split in two")}>Split in the middle</button>
              {stories[i + 1]?.kind === "story" && <button type="button" className="btn btn-small" disabled={busy}
                onClick={() => act(() => studio.mergeStories(projectId, [s.id, stories[i + 1].id]), "Merged")}>Merge with next</button>}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
