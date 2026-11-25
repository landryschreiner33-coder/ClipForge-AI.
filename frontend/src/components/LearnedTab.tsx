import { useCallback, useEffect, useState } from "react";
import { errorText } from "../api";
import { Learned, learnedApi, LearnedCheck, LearnedItem, LearnedVersion } from "../brain";
import { ConfirmDialog, EmptyState, Icon, Pill, toast, Toggle } from "./ui";

const KIND_WORD: Record<string, string> = { trim: "Trims", framing: "Framing", captions: "Captions", pacing: "Pacing",
  title: "Title picks", feedback: "Thumbs up or down" };
const STATUS: Record<LearnedItem["status"], [string, "good" | "info" | "neutral"]> = {
  in_use: ["In use", "good"], trying: ["Being checked", "info"], off: ["Off", "neutral"] };
const FORMAT_WORD: Record<string, string> = { highlights: "Highlights", story: "Full stories", stories: "Stories",
  live: "Live clips", tutorial: "Tutorials" };
const CHOICES: Record<string, { value: string | boolean; label: string }[]> = {
  caption_style: ["clean", "bold", "high_energy", "minimal"].map((v) => ({ value: v, label: v.replace("_", " ") })),
  caption_position: ["bottom", "middle", "top"].map((v) => ({ value: v, label: v })),
  tracking: ["auto", "center", "face", "speaker", "screen", "manual"].map((v) => ({ value: v, label: v })),
  layout: ["fill", "fit", "split", "pip", "game", "auto"].map((v) => ({ value: v, label: v })),
  silence: ["off", "light", "aggressive"].map((v) => ({ value: v, label: v })),
  title_kind: [{ value: "search", label: "Searchable" }, { value: "curiosity", label: "Curiosity" },
    { value: "moment", label: "The moment" }],
  highlight_words: [{ value: true, label: "on" }, { value: false, label: "off" }],
  captions_enabled: [{ value: true, label: "on" }, { value: false, label: "off" }],
  remove_fillers: [{ value: true, label: "on" }, { value: false, label: "off" }],
};
const date = (at: number) => new Date(at * 1000).toLocaleString(undefined, { month: "short", day: "numeric",
  hour: "numeric", minute: "2-digit" });

/** The check's numbers in a line: before and after, and by format when there is more than one. */
function CheckLine({ ev }: { ev: LearnedCheck | Record<string, never> }) {
  if (!("summary" in ev) || !ev.summary) return null;
  const formats = Object.entries(ev.by_format || {});
  return (
    <p className="tiny muted learned-check">
      <Icon name={ev.passed ? "check" : "info"} className="xs" />Checked on {ev.n} clip{ev.n === 1 ? "" : "s"}: {ev.summary}.
      {formats.length > 1 && <> By format: {formats.map(([f, r]) => `${FORMAT_WORD[f] || f} ${r.n} (${fmt(r.before, ev.unit)} → ${fmt(r.after, ev.unit)})`).join(", ")}.</>}
    </p>
  );
}
const fmt = (v: number, unit: string) => unit === "share" ? `${Math.round((1 - v) * 100)}%` : `${v.toFixed(2)}${unit}`;

/**
 * Brain → Learned: what ClipForge learned from your edits (trims, framing, captions, pacing, title picks) and your
 * thumbs up or down. Explicit preferences are ones you set; inferred ones are trends in your edits, used only after
 * a check on your own edited clips shows they get closer to what you do. Every change is a version you can go back to.
 */
export function LearnedTab() {
  const [v, setV] = useState<Learned | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<{ item: LearnedItem; value: string } | null>(null);
  const [removing, setRemoving] = useState<LearnedItem | null>(null);
  const [rolling, setRolling] = useState<LearnedVersion | null>(null);
  const [forgetting, setForgetting] = useState(false);
  const load = useCallback(async () => {
    try { setV(await learnedApi.view()); setProblem(""); } catch (e) { setProblem(errorText(e)); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const run = async (fn: () => Promise<Learned>, done?: string) => {
    setBusy(true);
    try { setV(await fn()); if (done) toast(done); } catch (e) { toast(errorText(e), true); await load(); }
    setBusy(false);
  };

  if (!v) return problem ? <p className="error-text"><Icon name="alert" />{problem}</p> : <p className="muted">Loading what ClipForge learned…</p>;
  const edits = Object.entries(v.observed).filter(([k]) => k !== "feedback").reduce((n, [, c]) => n + c, 0);
  const valueWord = (item: LearnedItem) => {
    const c = CHOICES[item.key]?.find((o) => o.value === item.value);
    if (c) return c.label;
    if (item.key.endsWith("_shift")) return `${Number(item.value) > 0 ? "+" : ""}${item.value} s`;
    return String(item.value);
  };
  const row = (item: LearnedItem) => (
    <li key={item.id} className={`learned-item ${item.status}`}>
      <div className="row wrap learned-item-head">
        <b className="grow">{item.text}</b>
        <Pill tone={STATUS[item.status][1]}>{STATUS[item.status][0]}</Pill>
      </div>
      <p className="tiny muted">{v.keys[item.key] || item.key}: {valueWord(item)}
        {item.source === "inferred" ? ` · from ${item.evidence} edited clip${item.evidence === 1 ? "" : "s"}` : " · set by you"}
        {item.version > 1 ? ` · changed ${item.version - 1} time${item.version === 2 ? "" : "s"}` : ""}</p>
      <CheckLine ev={item.evaluation} />
      <div className="row wrap">
        <Toggle on={item.status === "in_use"} disabled={busy} label="Use for new clips"
          onChange={(on) => void run(() => learnedApi.status(item.id, on ? "in_use" : "off"), on ? "Used for new clips." : "Turned off.")} />
        <button type="button" className="btn btn-small btn-quiet" disabled={busy}
          onClick={() => setEditing({ item, value: JSON.stringify(item.value) })}><Icon name="edit" />Change</button>
        <button type="button" className="btn btn-small btn-quiet" disabled={busy} onClick={() => setRemoving(item)}>
          <Icon name="trash" />Delete</button>
      </div>
    </li>
  );
  const pct = (x: number | null) => x == null ? "–" : `${Math.round(x * 100)}%`;
  return (
    <div className="stack-3 learned-page">
      <p className="muted">What ClipForge learned from your edits: where you move a clip's start and end, how you frame it,
        caption it and cut its pauses, and which title you pick. A habit is written down when {v.rules_text.min_evidence} or more
        clips agree, checked on your own edited clips (one left out at a time), and used for new clips only when it gets at least
        {" "}{Math.round(v.rules_text.promote * 100)}% closer to what you do on {v.rules_text.eval_min} or more clips. Publishing rules, accounts,
        spending limits and daily targets are never learned. It stays on this computer.</p>
      {problem && <p className="error-text"><Icon name="alert" />{problem}</p>}

      <section className="panel tight" aria-labelledby="learned-on">
        <div className="panel-head"><h3 id="learned-on">Learning from your edits</h3>
          <Pill tone={v.on ? "good" : "neutral"}>{v.on ? "On" : "Off"}</Pill></div>
        <div className="row wrap">
          <Toggle on={v.on} disabled={busy} label="Learn from my edits and use what is proven"
            onChange={(on) => void run(() => learnedApi.switch(on), on ? "Learning from your edits again." : "Off: nothing is recorded and nothing learned is used.")} />
          <button type="button" className="btn btn-small" disabled={busy || !v.on}
            onClick={() => void run(learnedApi.check, "Checked again on your edited clips.")}><Icon name="refresh" />Check again now</button>
          {edits + (v.observed.feedback || 0) > 0 && <button type="button" className="btn btn-small btn-quiet" disabled={busy}
            onClick={() => setForgetting(true)}><Icon name="x" />Forget my edits</button>}
        </div>
        <div className="mem-meta">
          <span>{edits} edit{edits === 1 ? "" : "s"} read</span>
          {Object.entries(v.observed).map(([k, n]) => <span key={k}>{n} {(KIND_WORD[k] || k).toLowerCase()}</span>)}
        </div>
      </section>

      <section className="panel tight" aria-labelledby="learned-explicit">
        <div className="panel-head"><h3 id="learned-explicit">Set by you</h3><Pill tone="info">{v.explicit.length}</Pill></div>
        <p className="small muted">Preferences you set or changed here. They win over any trend, and a trend never changes them.
          Rules you tell ClipForge AI in a chat are in <a className="textlink" href="#/brain/memory">Brain → Memory</a> ({v.rules} on).</p>
        {v.explicit.length ? <ul className="learned-list">{v.explicit.map(row)}</ul>
          : <p className="small muted">None yet. Change a learned preference to make it yours.</p>}
      </section>

      <section className="panel tight" aria-labelledby="learned-inferred">
        <div className="panel-head"><h3 id="learned-inferred">Trends in your edits</h3><Pill tone="info">{v.inferred.length}</Pill></div>
        {v.inferred.length ? <ul className="learned-list">{v.inferred.map(row)}</ul> : (
          <EmptyState icon="brain" title="No habits yet" level={3}>
            Edit a few clips in the clip editor. When {v.rules_text.min_evidence} clips agree (for example, you always start them a
            second earlier), the habit shows here with its check.
          </EmptyState>)}
      </section>

      <section className="panel tight" aria-labelledby="learned-taste">
        <div className="panel-head"><h3 id="learned-taste">Clip choices and Clip Scores</h3>
          <Pill tone={v.taste.used ? (v.taste.ready ? "good" : "info") : "neutral"}>{!v.taste.used ? "Off" : v.taste.ready ? "Moving scores" : "Learning"}</Pill></div>
        <p className="small muted">The clips you keep, leave out, export or publish (and your thumbs up or down) teach ClipForge which
          moments you like; once it has enough, each new clip's score moves a little your way.</p>
        <p className="small">{v.taste.events} choice{v.taste.events === 1 ? "" : "s"} ({v.taste.kept} kept, {v.taste.left_out} left out).
          {v.taste.preferences.length > 0 && ` You tend to keep clips with ${v.taste.preferences.join(", ")}.`}</p>
        <p className="small"><Icon name={v.taste.check.passed ? "check" : "info"} className="xs" />Check: {v.taste.check.summary}
          {v.taste.check.before != null && ` (${pct(v.taste.check.before)} → ${pct(v.taste.check.after)})`}.</p>
        <Toggle on={v.taste.used} disabled={busy} label="Let my clip choices move Clip Scores"
          onChange={(on) => void run(() => learnedApi.taste(on), on ? "Your clip choices move Clip Scores again." : "Clip Scores no longer move with your choices.")} />
      </section>

      <section className="panel tight" aria-labelledby="learned-versions">
        <div className="panel-head"><h3 id="learned-versions">Versions</h3><Pill tone="info">{v.versions.length}</Pill></div>
        <p className="small muted">Every change to what is used is a version: the preferences, whether clip choices move scores, and the
          words of your rules for ClipForge AI. Going back puts them as they were; anything added since is turned off, not deleted.</p>
        {v.versions.length ? (
          <ol className="learned-versions">
            {v.versions.map((ver, i) => (
              <li key={ver.id}>
                <div className="row wrap">
                  <b className="grow">Version {ver.number}: {ver.what}</b>
                  <span className="tiny muted">{date(ver.created_at)}</span>
                  {i > 0 && <button type="button" className="btn btn-small btn-quiet" disabled={busy}
                    onClick={() => setRolling(ver)}><Icon name="back" />Go back to this</button>}
                </div>
                <p className="tiny muted">{ver.in_use.length ? `In use: ${ver.in_use.join("; ")}` : "Nothing learned in use"}
                  {ver.taste ? "" : " · clip choices off"}</p>
              </li>))}
          </ol>) : <p className="small muted">No versions yet.</p>}
      </section>

      {editing && <ConfirmDialog title={`Change: ${v.keys[editing.item.key] || editing.item.key}`} confirmLabel="Use this"
        onClose={() => setEditing(null)} onConfirm={() => {
          const e = editing; setEditing(null);
          void run(() => learnedApi.change(e.item.id, JSON.parse(e.value)), "Saved as yours and used for new clips.");
        }}>
        <p className="small muted">{editing.item.text}. What you set here is yours: a trend never changes it.</p>
        {CHOICES[editing.item.key] ? (
          <label className="field"><span>Value</span>
            <select value={editing.value} onChange={(ev) => setEditing({ ...editing, value: ev.target.value })}>
              {CHOICES[editing.item.key].map((o) => <option key={String(o.value)} value={JSON.stringify(o.value)}>{o.label}</option>)}
            </select></label>
        ) : (
          <label className="field"><span>{editing.item.key.endsWith("_shift") ? "Seconds (minus is earlier, at most 3)" : "Value"}</span>
            <input type="number" step={0.1} value={Number(JSON.parse(editing.value))}
              onChange={(ev) => setEditing({ ...editing, value: JSON.stringify(Number(ev.target.value)) })} /></label>
        )}
      </ConfirmDialog>}
      {removing && <ConfirmDialog title="Delete this preference?" danger confirmLabel="Delete" onClose={() => setRemoving(null)}
        onConfirm={() => { const r = removing; setRemoving(null); void run(() => learnedApi.remove(r.id), "Deleted. Go back a version to undo."); }}>
        <p>“{removing.text}” is no longer used. {removing.source === "inferred" ? "If your edits keep showing it, it is written down again and checked." : ""}
          {" "}The version list keeps it, so you can go back.</p>
      </ConfirmDialog>}
      {forgetting && <ConfirmDialog title="Forget the edits ClipForge read?" danger confirmLabel="Forget" onClose={() => setForgetting(false)}
        onConfirm={() => { setForgetting(false); void run(learnedApi.forgetEdits, "Forgotten. It learns again from your next edits."); }}>
        <p>The edits and thumbs it read, and the trends written from them, are deleted. What you set yourself stays. Clip choices
          for Clip Scores are separate: forget those in Brain → Memory.</p>
      </ConfirmDialog>}
      {rolling && <ConfirmDialog title={`Go back to version ${rolling.number}?`} confirmLabel="Go back" onClose={() => setRolling(null)}
        onConfirm={() => { const r = rolling; setRolling(null); void run(() => learnedApi.rollback(r.number), `Back to version ${r.number}.`); }}>
        <p>What is used becomes what it was then: {rolling.in_use.length ? rolling.in_use.join("; ") : "nothing learned"}
          {rolling.taste ? "" : ", clip choices not moving scores"}. Rules for ClipForge AI go back to their words then; rules told since are
          turned off. This is a new version, so you can come back.</p>
      </ConfirmDialog>}
    </div>
  );
}
