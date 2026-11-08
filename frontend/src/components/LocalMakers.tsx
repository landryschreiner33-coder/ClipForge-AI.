import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api";
import { EngineModel, EngineRole, engines, EnginesView } from "../studio";
import { Banner, ConfirmDialog, Disclosure, Icon, Pill, ProgressBar, Segmented, toast } from "./ui";

const gb = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(n / 1e6))} MB`);
const ROLE_NAME: Record<EngineRole, string> = { image: "Pictures", video: "Video clips", voice: "Voice" };

/**
 * Settings → Pictures, video, voice: the makers that run on this computer. Pictures and short video clips come from
 * ComfyUI (a free, open-source program: ClipForge's own copy, set up from here, or the ComfyUI app if it is already
 * installed) with free models whose licences allow commercial use; the voice runs inside ClipForge. Every download is
 * pinned and checked, and nothing made here leaves the computer. The animated-shorts maker and the AI use them.
 */
export default function LocalMakersSettings() {
  const [st, setSt] = useState<EnginesView | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState("");
  const [voice, setVoice] = useState("F1");
  const [confirm, setConfirm] = useState<null | { what: "comfyui" | "model"; model?: EngineModel }>(null);

  const load = useCallback(async () => {
    try {
      const v = await engines.view();
      setSt(v);
      setProblem("");
      return v;
    } catch (e) {
      setProblem(errorText(e));
      return null;
    }
  }, []);
  useEffect(() => { void load().then((v) => { if (v) setUrl(v.comfyui.url); }); }, [load]);
  const running = st?.task.state === "running" || st?.trial.state === "running";
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => { void load(); }, 1500);
    return () => window.clearInterval(t);
  }, [running, load]);

  const act = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    try {
      await fn();
      await load();
      if (done) toast(done);
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
  };
  const save = (patch: Record<string, unknown>) => act(() => api.saveSettings(patch), "Saved.");

  if (problem) return <Banner tone="bad" title="Could not read the makers">{problem}</Banner>;
  if (!st) return <p className="small muted">Loading…</p>;
  if (st.online) return <Banner tone="info" title="Part of the desktop app">Pictures, video clips and the voice are made
    on your own computer by the desktop app. The online studio does not offer them.</Banner>;

  const c = st.comfyui;
  const t = st.task;
  const setupRunning = t.state === "running";
  const trial = st.trial;
  const byRole = (role: EngineRole) => st.models.filter((m) => m.role === role);
  const voiceModel = byRole("voice")[0];
  const comfyReady = c.mode === "clipforge" ? c.installed : c.mode === "app" ? Boolean(c.app_found) : false;

  // the reasons name this page for other pages (the shorts maker); here that hint is redundant
  const why = (role: EngineRole) => st.roles[role].why.replace(/ \(Settings, Pictures, video, voice\)/, "");

  const fitNote = (m: EngineModel) => {
    if (m.fit === "slow" && c.flavor === "mps") {
      return `This Mac has ${Math.round(st.memory_mb / 1024)} GB of memory, so this one will be slow here.`;
    }
    if (m.fit === "slow") return `This graphics card has ${Math.round(st.vram_mb / 1024)} GB, so this one will be slow here.`;
    if (m.fit === "cpu") return "No graphics this computer can use for it was found, so it would be very slow here.";
    return "";
  };

  const modelRow = (m: EngineModel) => {
    const chosen = st.chosen[m.role] === m.id || (!st.chosen[m.role] && st.roles[m.role].model === m.id);
    return (
      <li key={m.id} className="file-row"><Icon name={m.role === "image" ? "spark" : m.role === "video" ? "film" : "play"} />
        <div><b>{m.name}</b> <span className="small muted">by {m.maker} · <a href={m.licence_url} target="_blank"
          rel="noreferrer">{m.licence}</a></span>
          <span className="block small">{m.about}</span>
          <span className="block small muted">{m.ready ? "Downloaded" : `Download: ${gb(m.download_bytes || m.bytes)}`}
            {m.memory_gb ? ` · runs well on a Mac with ${m.memory_gb} GB of memory or a PC with an NVIDIA card with ${m.vram_gb} GB` : ""}</span>
          {fitNote(m) && <span className="block small">{fitNote(m)}</span>}</div>
        {m.ready ? <Pill tone="good" icon="check">{chosen && byRole(m.role).length > 1 ? "In use" : "Ready"}</Pill>
          : m.recommended ? <Pill tone="info">Best for this computer</Pill> : <Pill>Not downloaded</Pill>}
        <div className="row-actions">
          {m.ready && byRole(m.role).length > 1 && !chosen && <button type="button" className="btn btn-small" disabled={busy}
            onClick={() => void save({ [m.role === "image" ? "engines_picture" : m.role === "video" ? "engines_video" : "engines_voice"]: m.id })}>
            Use this</button>}
          {!m.ready && m.can_download && <button type="button" className="btn btn-small" disabled={busy || setupRunning ||
            (m.role !== "voice" && !comfyReady)} onClick={() => setConfirm({ what: "model", model: m })}>
            <Icon name="download" />Download</button>}
          {m.ready && m.removable && <button type="button" className="btn btn-small btn-quiet" disabled={busy || setupRunning}
            onClick={() => void act(() => engines.remove("model", m.id), `${m.name} removed.`)}><Icon name="trash" />Remove</button>}
        </div></li>
    );
  };

  const tryRow = (role: EngineRole) => {
    const ready = st.roles[role].ready;
    const mine = trial.role === role;
    return (
      <div className="row-actions">
        <button type="button" className="btn btn-small" disabled={!ready || busy || trial.state === "running"}
          title={ready ? undefined : why(role)}
          onClick={() => void act(() => engines.tryIt(role, "", role === "voice" ? voice : ""))}>
          <Icon name="play" />{role === "image" ? "Make a test picture" : role === "video" ? "Make a 2-second test clip" : "Hear it"}</button>
        {mine && trial.state === "running" && <button type="button" className="btn btn-small btn-quiet"
          onClick={() => void act(() => engines.stopTry())}><Icon name="stop" />Stop</button>}
        {!ready && <span className="small muted">{why(role)}</span>}
      </div>
    );
  };

  const trialResult = (role: EngineRole) => {
    if (trial.role !== role || trial.state === "idle") return null;
    if (trial.state === "running") {
      return <div><ProgressBar value={trial.progress} label={`Making the ${ROLE_NAME[role].toLowerCase()} test`} />
        <p className="small muted">{trial.message}</p></div>;
    }
    if (trial.state === "failed") return <Banner tone="bad" title="The test did not work">{trial.error}</Banner>;
    if (trial.state === "canceled") return <p className="small muted">Stopped.</p>;
    return (
      <div className="maker-result">
        {role === "image" && <img src={trial.file} alt="The test picture" style={{ maxWidth: 240, borderRadius: 8 }} />}
        {role === "video" && <video src={trial.file} controls loop muted style={{ maxWidth: 240, borderRadius: 8 }} />}
        {role === "voice" && <audio src={trial.file} controls />}
        <p className="small muted">Made on this computer in {trial.seconds} seconds.</p>
      </div>
    );
  };

  return (
    <>
      <section className="panel" aria-labelledby="lm-what"><h2 id="lm-what">Pictures, video and voice on this computer</h2>
        <p className="small">ClipForge can make pictures, short video clips and voice-overs itself, on this computer, for free:
          the animated-shorts maker and ClipForge AI use them. Pictures and clips are made by ComfyUI, a free, open-source
          program, with models whose licences allow commercial use. The voice runs inside ClipForge. Once downloaded,
          nothing goes online and nothing you make leaves the computer.</p>
        {(["image", "video", "voice"] as EngineRole[]).map((r) => (
          <p key={r} className="small">{st.roles[r].ready ? <Pill tone="good" icon="check">{ROLE_NAME[r]}</Pill> :
            <Pill>{ROLE_NAME[r]}</Pill>} {st.roles[r].ready ? st.roles[r].engine : why(r)}</p>
        ))}
      </section>

      <section className="panel" aria-labelledby="lm-comfy"><h2 id="lm-comfy">ComfyUI (pictures and video)</h2>
        <Segmented value={c.mode} disabled={busy || setupRunning} label="Which ComfyUI makes pictures and video"
          onChange={(mode) => void save({ engines_comfyui: mode })} options={[
            { value: "clipforge", label: "ClipForge's own" },
            { value: "app", label: "The ComfyUI app on this computer" },
            { value: "off", label: "Off" }]} />
        {c.mode === "clipforge" && <>
          <p className="small muted">ClipForge downloads ComfyUI {c.version} with a private Python of its own and keeps it in
            its own folder; nothing else on the computer changes. It starts when a picture or clip is needed and stops after
            {" "}{c.idle_minutes} minutes without work.{c.flavor_label ? ` On this computer it uses ${c.flavor_label}.` : ""}</p>
          {!c.supported && <Banner tone="warn" title="Not available on this computer">ClipForge can set ComfyUI up on a Mac with
            Apple silicon or a 64-bit Windows or Linux PC.</Banner>}
          {c.mac_too_old && <Banner tone="warn" title="macOS 14 or newer is needed">Update macOS in System Settings, General,
            Software Update, then set ComfyUI up.</Banner>}
          {c.flavor === "cpu" && c.gpu?.name && <Banner tone="info" title="Update the NVIDIA driver for speed">{c.gpu.name} needs
            driver 580 or newer for ComfyUI to use it (this one is {c.gpu.driver || "unknown"}). Without it, pictures are made on
            the processor, which is much slower.</Banner>}
          <p className="small">{c.installed ? <Pill tone="good" icon="check">Set up</Pill> : <Pill>Not set up</Pill>}
            {" "}{c.installed ? (c.running ? "Running now." : "Starts when needed.") :
              `About ${gb(c.download_bytes)} to download, ${gb(c.disk_bytes)} on disk.`}</p>
          <div className="row-actions">
            {!c.installed && c.supported && !c.mac_too_old && <button type="button" className="btn" disabled={busy || setupRunning}
              onClick={() => setConfirm({ what: "comfyui" })}><Icon name="download" />Set up ComfyUI ({gb(c.download_bytes)})</button>}
            {c.installed && <button type="button" className="btn btn-quiet" disabled={busy || setupRunning}
              onClick={() => void act(() => engines.remove("comfyui"), "ComfyUI removed. Your models were kept.")}>
              <Icon name="trash" />Remove ComfyUI</button>}
          </div>
        </>}
        {c.mode === "app" && <>
          <p className="small muted">Use the ComfyUI app (or a ComfyUI you installed yourself) while it is open. ClipForge looks
            on this computer at port 8000 (the ComfyUI app) and 8188, or at the address below.</p>
          <p className="small">{c.app_found ? <><Pill tone="good" icon="check">Found</Pill> ComfyUI at {c.app_found}</> :
            <><Pill>Not running</Pill> Open the ComfyUI app, then check again.</>}</p>
          <div className="row-actions">
            <label className="field"><span>Address (optional)</span><input value={url} placeholder="http://127.0.0.1:8000"
              onChange={(e) => setUrl(e.target.value)} /></label>
            <button type="button" className="btn btn-small" disabled={busy} onClick={() => void save({ engines_comfyui_url: url.trim() })}>
              Save and check</button>
            <button type="button" className="btn btn-small btn-quiet" disabled={busy} onClick={() => void load()}>
              <Icon name="refresh" />Check again</button>
          </div>
        </>}
        {c.mode === "off" && <p className="small muted">ClipForge makes no pictures or clips. The shorts maker uses your own
          pictures and video, and plain coloured scenes.</p>}
        {setupRunning && <div><ProgressBar value={t.total ? t.done / t.total : 0} label={t.what} />
          <p className="small muted">{t.what}: {t.status}{t.total ? ` (${gb(t.done)} of ${gb(t.total)})` : ""}{t.steps > 1 ?
            ` · step ${t.step} of ${t.steps}` : ""}</p>
          <button type="button" className="btn btn-small btn-quiet" onClick={() => void act(() => engines.cancel())}>
            <Icon name="stop" />Cancel</button></div>}
        {t.state === "failed" && t.error && <Banner tone="bad" title={`${t.what || "The set-up"} stopped`}>{t.error}</Banner>}
        {t.state === "canceled" && <p className="small muted">Stopped. Downloads resume where they stopped.</p>}
      </section>

      {(["image", "video"] as EngineRole[]).map((role) => (
        <section key={role} className="panel" aria-labelledby={`lm-${role}`}>
          <h2 id={`lm-${role}`}>{ROLE_NAME[role]}</h2>
          {byRole(role).length ? <ul className="file-list">{byRole(role).map(modelRow)}</ul> :
            <p className="small muted">No model for this yet.</p>}
          {c.mode !== "off" && !comfyReady && <p className="small muted">Set up ComfyUI above first.</p>}
          {c.mode === "app" && c.app_found && byRole(role).some((m) => !m.can_download) &&
            <p className="small muted">That ComfyUI is on another computer: download the model in it yourself.</p>}
          {tryRow(role)}
          {trialResult(role)}
        </section>
      ))}

      <section className="panel" aria-labelledby="lm-voice"><h2 id="lm-voice">Voice</h2>
        {voiceModel && <ul className="file-list">{modelRow(voiceModel)}</ul>}
        <Banner tone="neutral" title="The voice's licence">{voiceModel?.rule || st.voice_rule}</Banner>
        {voiceModel?.ready && <div className="row-actions">
          <label className="field"><span>Voice to hear</span>
            <select value={voice} onChange={(e) => setVoice(e.target.value)}>
              {["F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5"].map((v) => (
                <option key={v} value={v}>{v.startsWith("F") ? "Woman" : "Man"} {v.slice(1)}</option>))}
            </select></label>
        </div>}
        {tryRow("voice")}
        {trialResult("voice")}
      </section>

      <Disclosure summary="Where everything is kept, and what each part is">
        <ul className="small">
          <li>ComfyUI and its Python: ClipForge&apos;s data folder, tools/comfy. Models: the models folder, comfy (pictures and
            video) and voice. Everything made here: engines/made, with a note next to each file saying which model made it,
            its licence, the words and the seed.</li>
          <li>ComfyUI {c.version} is GPL-3.0 open source (<a href={c.source} target="_blank" rel="noreferrer">its source</a>). It
            runs as a separate program that ClipForge talks to on this computer only.</li>
          <li>Each download has a fixed address, size and checksum. A file that does not match is deleted and never used.</li>
        </ul>
      </Disclosure>

      {confirm && <ConfirmDialog title={confirm.what === "comfyui" ? "Set up ComfyUI?" : `Download ${confirm.model?.name}?`}
        confirmLabel={confirm.what === "comfyui" ? `Set up (${gb(c.download_bytes)})`
          : `${confirm.model?.rule ? "Agree and download" : "Download"} (${gb(confirm.model?.download_bytes || 0)})`}
        onClose={() => setConfirm(null)} disabled={busy}
        onConfirm={async () => {
          // the button the person pressed shows the model's use rules, so pressing it is agreeing to them
          await engines.setUp(confirm.what, confirm.model?.id || "", Boolean(confirm.model?.rule));
          await load();
        }}>
        {confirm.what === "comfyui" ? <p>ClipForge downloads ComfyUI {c.version}, a Python for it and PyTorch for
          {" "}{c.flavor_label || "this computer"}: about {gb(c.download_bytes)}, {gb(c.disk_bytes)} on disk. It can take a while;
          you can keep working, and a stopped download resumes.</p> :
          <><p>{confirm.model?.about} {confirm.model?.name} is made by {confirm.model?.maker} and comes under
            {" "}<a href={confirm.model?.licence_url} target="_blank" rel="noreferrer">{confirm.model?.licence}</a>.</p>
            {confirm.model?.rule && <p><b>Its use rules:</b> {confirm.model.rule}</p>}
            <p>About {gb(confirm.model?.download_bytes || 0)} to download.</p></>}
      </ConfirmDialog>}
    </>
  );
}
