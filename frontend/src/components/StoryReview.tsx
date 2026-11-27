import { useCallback, useEffect, useState } from "react";
import { errorText } from "../api";
import { fmtTime, Snapshot, Story, STORY_MAX_S, studio } from "../studio";
import { UsedFromBrain } from "./studioParts";
import { Banner, Icon, Pill, toast } from "./ui";

const WORDS = { complete: ["good", "Boundaries look right"], uncertain: ["warn", "Worth a look"], incomplete: ["bad", "May be cut off"] } as const;

/** Full stories review: chronological story cards and the gaps between them, with simple boundary controls. Every
 * story (or, with Story parts, every part of a story) is already being made into its own clip; the cards are for
 * checking and fixing a boundary afterwards. No story clip can be made longer than five minutes here. */
export default function StoryReview({ projectId, version, onChange }: { projectId: string; version: number; onChange: () => void }) {
  const [stories, setStories] = useState<Story[] | null>(null);
  const [split, setSplit] = useState<"whole" | "parts">("whole");
  const [summary, setSummary] = useState<Record<string, any>>({});
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => studio.stories(projectId)
    .then((r) => { setStories(r.stories); setSummary(r.summary || {}); setSplit(r.split === "parts" ? "parts" : "whole"); })
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
  const waiting = stories.filter((s) => s.kind === "story" && !s.clip_id && s.included);
  const changed = waiting.some((s) => s.boundary_revision > 0);
  const count = stories.filter((s) => s.kind === "story").length;
  const inParts = stories.some((s) => s.parts > 1);
  const tooLong = (seconds: number) => seconds > STORY_MAX_S + 0.001;
  const longer = `A story clip can be at most ${fmtTime(STORY_MAX_S)} long`;
  const ai = (summary.ai || {}) as { asked?: number; changed?: number; provider?: string };
  return (
    <section className="panel" aria-labelledby="stories-title">
      <div className="panel-head">
        <h2 id="stories-title">Stories</h2>
        {waiting.length > 0 && <button type="button" className="btn btn-primary" disabled={busy}
          onClick={() => act(() => studio.createStoryClips(projectId, waiting.map((s) => s.id)), `${waiting.length} story clip${waiting.length > 1 ? "s" : ""} started`)}>
          <Icon name="film" />{changed ? "Remake" : "Make"} {waiting.length} clip{waiting.length > 1 ? "s" : ""}</button>}
      </div>
      <p className="small muted">
        {count > 0 ? (split === "parts"
          ? "Story parts: every story is cut at its best moments, and each part is its own clip with “Part 1”, “Part 2”… at the top. "
          : "Every story is its own clip, from where it starts to where the next one starts. ") : ""}
        {count > 0 ? `No story clip is longer than ${fmtTime(STORY_MAX_S)}${split === "parts" || !inParts ? "" : ": a longer story is split at its best point into parts"}. ` : ""}
        {summary.method ? `Boundaries are a ${summary.method}. ` : ""}
        {ai.asked ? `ClipForge AI checked ${ai.asked} of them. ` : ""}
        {count > 0 ? "If one is off, move it here and remake that clip." : ""}
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
              {s.parts > 1 && <Pill tone="accent" icon="film">Part {s.part} of {s.parts}</Pill>}
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
                  onClick={() => act(() => studio.createStoryClips(projectId, [s.id]), "Clip started")}>{s.boundary_revision > 0 ? "Remake this clip" : "Make this clip"}</button>}
              <button type="button" className="btn btn-small" disabled={busy} onClick={() => act(() => studio.patchStory(s.id, { included: !s.included }), s.included ? "Left out" : "Included")}>
                {s.included ? "Leave out" : "Include"}</button>
              <button type="button" className="btn btn-small" disabled={busy || tooLong(s.duration + 2)}
                title={tooLong(s.duration + 2) ? longer : undefined}
                onClick={() => act(() => studio.patchStory(s.id, { start: Math.max(0, s.start - 2) }), "Starts 2 s earlier")}>Start 2 s earlier</button>
              <button type="button" className="btn btn-small" disabled={busy || tooLong(s.duration + 2)}
                title={tooLong(s.duration + 2) ? longer : undefined}
                onClick={() => act(() => studio.patchStory(s.id, { end: s.end + 2 }), "Ends 2 s later")}>End 2 s later</button>
              <button type="button" className="btn btn-small" disabled={busy || s.duration < 10} onClick={() => act(() => studio.splitStory(projectId, s.id, (s.start + s.end) / 2), "Split in two")}>Split in the middle</button>
              {stories[i + 1]?.kind === "story" && <button type="button" className="btn btn-small"
                disabled={busy || tooLong(stories[i + 1].end - s.start)}
                title={tooLong(stories[i + 1].end - s.start) ? `${longer}, so these stay separate parts` : undefined}
                onClick={() => act(() => studio.mergeStories(projectId, [s.id, stories[i + 1].id]), "Merged")}>Merge with next</button>}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
