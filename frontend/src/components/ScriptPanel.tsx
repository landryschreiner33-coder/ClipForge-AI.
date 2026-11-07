import { useState } from "react";
import { errorText } from "../api";
import { Plan, Script, ScriptMatch, studio, Video } from "../studio";
import { ScriptDrop } from "./ScriptDrop";
import { Disclosure, Icon, toast } from "./ui";
import "./longVideo.css";

const STATUS_WORDS: Record<ScriptMatch["status"], string> = { matched: "found", weak: "found only partly", missing: "not in the footage",
  skipped: "too short to look for", heading: "chapter", direction: "never said" };

function quality(q: number | undefined): string {
  if (q === undefined || q === null) return "";
  return q >= 0.85 ? "said cleanly" : q >= 0.65 ? "a few slips" : "said roughly";
}

/** Script: every line of the script with where it plays, the other takes to swap in (Use this take), and the
 * script itself to change or take away (each a new version you can undo). Shown on the editor page. */
export function ScriptPanel({ v, plan, busy, edit, onStarted, onSelect }: { v: Video; plan: Plan; busy: boolean;
  edit: (change: Record<string, unknown>) => Promise<void>; onStarted: () => void; onSelect: (clipId: string) => void }) {
  const script = v.script;
  const matches = Object.fromEntries((plan.script?.lines || []).map((m) => [m.n, m]));
  const [changing, setChanging] = useState(false);
  const [draft, setDraft] = useState<Script | null>(null);
  const [starting, setStarting] = useState(false);
  const running = v.jobs.some((j) => j.kind === "video_smart" && (j.status === "running" || j.status === "queued"));
  const follow = async (s: Script | null) => {
    setStarting(true);
    try {
      await studio.setVideoScript(v.id, v.plan_revision, s);
      toast(s ? "Cutting the video to follow your script. The new version appears here when it is ready; Undo goes back."
        : "Cutting the video from your brief again, without the script.");
      setChanging(false);
      setDraft(null);
      onStarted();
    } catch (e) {
      toast(errorText(e), true);
    }
    setStarting(false);
  };
  const clipIndex = Object.fromEntries(plan.clips.map((c, i) => [c.id, i + 1]));
  const stats = plan.script?.stats;
  return (
    <section className="panel script-panel" aria-labelledby="vr-script">
      <div className="panel-head"><h2 id="vr-script">Script</h2>
        {script && plan.script && <span className="pill good">Followed</span>}
        {script && !plan.script && <span className="pill warn">Not followed yet</span>}</div>
      {!script && !changing && <>
        <p className="muted">Give ClipForge the script this video follows and it cuts one clip per line, in script order, with the best take of each line; the other takes stay behind it to swap in.</p>
        <button type="button" className="btn" disabled={busy || running} onClick={() => setChanging(true)}><Icon name="plus" />Add a script</button>
      </>}
      {changing && <div className="stack-3">
        <ScriptDrop value={draft} onChange={setDraft} compact />
        <div className="row-actions">
          <button type="button" className="btn btn-primary" disabled={!draft || starting || running} onClick={() => follow(draft)}><Icon name="create" />{running ? "Cutting…" : "Follow this script"}</button>
          <button type="button" className="btn" disabled={starting} onClick={() => { setChanging(false); setDraft(null); }}>Cancel</button>
        </div>
      </div>}
      {script && !changing && <>
        <p className="small muted">{script.filename}{stats ? ` · ${stats.matched + stats.weak} of ${stats.matched + stats.weak + stats.missing} lines found${stats.weak ? ` (${stats.weak} only partly)` : ""}${stats.missing ? ` · ${stats.missing} missing` : ""}${stats.alternatives ? ` · ${stats.alternatives} other take${stats.alternatives === 1 ? "" : "s"} to swap in` : ""}` : ""}</p>
        <ol className="script-lines" aria-label="Script lines and where they play">
          {script.lines.map((ln) => {
            const m = matches[ln.n];
            const status = m?.status || (ln.kind === "line" ? "missing" : ln.kind);
            const clip = m?.clip_id ? clipIndex[m.clip_id] : undefined;
            return (
              <li key={ln.n} className={`script-line ${ln.kind} ${ln.kind === "line" ? status : ""}`}>
                <span className="n">{ln.n}</span>
                <div className="break">
                  {ln.kind === "line" && m?.clip_id
                    ? <button type="button" className="link-btn" title={`Clip ${clip}: ${STATUS_WORDS[status as ScriptMatch["status"]]}`} onClick={() => onSelect(m.clip_id)}>{ln.speaker ? `${ln.speaker}: ` : ""}{ln.text}</button>
                    : <span>{ln.kind === "direction" ? `[${ln.text}]` : ln.text}</span>}
                  {ln.kind === "line" && <span className="block small muted">{STATUS_WORDS[status as ScriptMatch["status"]] || status}{clip ? ` · clip ${clip}` : ""}{m && m.status === "weak" ? ` · ${Math.round(m.coverage * 100)}% of the line` : ""}</span>}
                  {m && m.takes.length > 0 && <div className="script-takes">
                    {m.takes.map((t) => (
                      <button key={t.clip_id} type="button" className="btn btn-small" disabled={busy} title="Play this take of the line instead (the current one stays behind it, switched off)"
                        onClick={() => edit({ op: "use_take", clip_id: t.clip_id })}>Use this take{clipIndex[t.clip_id] ? ` (clip ${clipIndex[t.clip_id]}` : ""}{t.coverage < 1 ? `, ${Math.round(t.coverage * 100)}%` : ""}{quality(t.quality) ? `, ${quality(t.quality)}` : ""}{clipIndex[t.clip_id] ? ")" : ""}</button>
                    ))}
                  </div>}
                </div>
              </li>
            );
          })}
        </ol>
        <Disclosure summary="Change the script">
          <div className="stack-3">
            <p className="small muted">A new script cuts the video again to follow it; taking it away cuts from your brief again. Either way a new version is made and Undo goes back.</p>
            <div className="row-actions wrap">
              <button type="button" className="btn btn-small" disabled={busy || running} onClick={() => setChanging(true)}>Give another script</button>
              <button type="button" className="btn btn-small" disabled={busy || running || starting} onClick={() => follow(null)}>Take the script away</button>
              {!plan.script && <button type="button" className="btn btn-small btn-primary" disabled={busy || running || starting} onClick={() => follow(script)}>Follow the script now</button>}
            </div>
          </div>
        </Disclosure>
      </>}
    </section>
  );
}
