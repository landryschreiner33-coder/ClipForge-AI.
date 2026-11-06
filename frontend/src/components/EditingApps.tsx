import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api";
import { craft, CraftStatus } from "../studio";
import { Banner, Icon, Pill, ProgressBar, Segmented, Toggle, toast } from "./ui";

const mb = (n: number) => `${Math.max(1, Math.round(n / 1e6))} MB`;

/**
 * Settings → Editing apps: FilmCraft (video editor) and EffectCraft (motion graphics), the free open-source apps from
 * the ArtCraft team, inside ClipForge. ClipForge fetches the versions it was tested with from their GitHub releases
 * (each download is checked against its published checksum) and keeps them in its own folder; nothing else is
 * installed on the computer. Final videos are then edited and rendered in FilmCraft, with the built-in editor as
 * the backup.
 */
export default function EditingAppsSettings() {
  const [st, setSt] = useState<CraftStatus | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setSt(await craft.status());
      setProblem("");
    } catch (e) {
      setProblem(errorText(e));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const running = st?.task.state === "running";
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => { void load(); }, 1500);
    return () => window.clearInterval(t);
  }, [running, load]);

  const save = async (patch: Record<string, unknown>) => {
    setBusy(true);
    try {
      await api.saveSettings(patch);
      await load();
      toast("Saved.");
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
  };
  const install = async () => {
    setBusy(true);
    try {
      setSt(await craft.install());
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
  };

  if (problem) return <Banner tone="bad" title="Could not read the editing apps">{problem}</Banner>;
  if (!st) return <p className="small muted">Loading…</p>;
  const t = st.task;
  return (
    <>
      <section className="panel" aria-labelledby="ea-apps"><h2 id="ea-apps">Editing apps</h2>
        <p className="small">FilmCraft (a video editor) and EffectCraft (motion graphics) are free, open-source apps from the
          ArtCraft team. ClipForge keeps its own copy of the versions it was tested with, so they work inside ClipForge with
          nothing else to install: the AI edits your videos with FilmCraft&apos;s tools, EffectCraft makes effect shots such
          as the animated title, FilmCraft renders the final video, and FilmCraft&apos;s editor opens on the editor page.</p>
        {st.online && <Banner tone="info" title="Part of the desktop app">The online studio uses the built-in editor; its
          server does not fetch programs.</Banner>}
        {!st.online && !st.supported && <Banner tone="warn" title="Not available on this computer">FilmCraft has no release
          for this kind of computer, so ClipForge uses the built-in editor.</Banner>}
        <ul className="file-list">{st.apps.map((a) => (
          <li key={a.key} className="file-row"><Icon name={a.key === "filmcraft" ? "film" : "spark"} />
            <div><b>{a.label} {a.version}</b> <span className="small muted">{a.what}</span>
              <span className="block small muted">{a.cli.ready ? (a.cli.source === "clipforge" ? "Set up in ClipForge" :
                a.cli.source === "installed" ? "Using the FilmCraft app installed on this computer" : "Using a copy named in CLIPFOUNDRY settings")
                : `Not set up yet (${mb(a.cli.bytes + (a.web && !a.web.ready ? a.web.bytes : 0))})`}
                {a.web ? (a.web.ready ? " · its editor works on the editor page" : "") : ""}</span></div>
            {a.cli.ready ? <Pill tone="good" icon="check">Ready</Pill> : <Pill>Not set up</Pill>}
            <a className="btn btn-small" href={a.page} target="_blank" rel="noreferrer"><Icon name="external" />About</a></li>
        ))}</ul>
        {running && <div><ProgressBar value={t.total ? t.done / t.total : 0}
          label={`Downloading ${t.app} (${t.part})`} /><p className="small muted">Downloading {t.app === "filmcraft" ?
          "FilmCraft" : "EffectCraft"}{t.part === "web" ? "'s editor" : ""}: {mb(t.done)} of {mb(t.total)}</p></div>}
        {t.state === "failed" && t.error && <Banner tone="bad" title="Setting them up stopped">{t.error}</Banner>}
        {st.can_install && st.missing_bytes > 0 && !running && <div className="row-actions">
          <button type="button" className="btn" disabled={busy} onClick={() => void install()}><Icon name="download" />
            Set up FilmCraft and EffectCraft ({mb(st.missing_bytes)})</button></div>}
        {!st.online && <Toggle on={st.auto_install} disabled={busy} onChange={(on) => void save({ craft_auto_install: on })}
          label="Set them up automatically when ClipForge starts" />}
      </section>
      <section className="panel" aria-labelledby="ea-engine"><h2 id="ea-engine">Who makes the final video</h2>
        <Segmented value={st.engine} disabled={busy} label="Who makes the final video"
          onChange={(engine) => void save({ edit_engine: engine })} options={[
            { value: "auto", label: "FilmCraft, built-in as backup" },
            { value: "filmcraft", label: "FilmCraft only" },
            { value: "ffmpeg", label: "Built-in editor" }]} />
        <p className="small muted">{st.engine === "auto" ? "FilmCraft edits and renders final videos once it is set up. If it " +
          "cannot (it is an early release), the built-in editor makes that version and the video says why." :
          st.engine === "filmcraft" ? "Final videos are only made in FilmCraft; if FilmCraft cannot make one, the render " +
          "stops and says why." : "Final videos are made with ClipForge's built-in editor. FilmCraft's editor still opens on " +
          "the editor page."} Previews always use the built-in editor, so they stay quick, except versions you finished
          in FilmCraft&apos;s editor.</p>
        <Toggle on={st.ai_finish} disabled={busy} onChange={(on) => void save({ craft_ai_finish: on })}
          label="Let the AI finish edits with FilmCraft's tools and EffectCraft shots" />
        <p className="small muted">{st.ai_disclosure || "Needs ClipForge AI's model (Settings, ClipForge AI). Without one, FilmCraft " +
          "still makes ClipForge's look and sound and the animated title."} The AI can only use finishing tools (colour,
          effects and keyframes, transitions, speed, titles, caption style, sound) and at most two effect shots; it
          cannot cut, delete or name files.</p>
      </section>
    </>
  );
}
