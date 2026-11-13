import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api";
import { EngineCloudCommand, EngineModel, EngineRole, engines, EnginesView } from "../studio";
import { Banner, ConfirmDialog, Dialog, Disclosure, Icon, Pill, ProgressBar, Segmented, toast } from "./ui";

const gb = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(n / 1e6))} MB`);
const ROLE_NAME: Record<EngineRole, string> = { image: "Pictures", video: "Video clips", voice: "Voice" };

/**
 * Settings → Pictures, video, voice: the makers that run on this computer. Pictures and short video clips come from
 * ComfyUI (a free, open-source program: ClipForge's own copy, set up from here, or the ComfyUI app if it is already
 * installed, or a ComfyUI on a cloud computer the person rents by the hour, e.g. on RunPod) with free models whose
 * licences allow commercial use; the voice runs inside ClipForge. Every download is pinned and checked. On this computer
 * nothing made here leaves it; a cloud computer gets the words (and the picture a clip starts from) and sends back what
 * it made. The animated-shorts maker and the AI use them.
 */
export default function LocalMakersSettings() {
  const [st, setSt] = useState<EnginesView | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState("");
  const [voice, setVoice] = useState("F1");
  const [confirm, setConfirm] = useState<null | { what: "comfyui" | "model"; model?: EngineModel }>(null);
  const [cloudUrl, setCloudUrl] = useState("");
  const [cloudKey, setCloudKey] = useState("");
  // "Put it on your cloud computer": the model, then (once agreed to its use rules, if it has any) the command
  const [command, setCommand] = useState<null | { model: EngineModel; view: EngineCloudCommand | null; error: string }>(null);

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
  useEffect(() => { void load().then((v) => { if (v) { setUrl(v.comfyui.url); setCloudUrl(v.comfyui.remote?.url || ""); } }); }, [load]);
  const running = st?.task.state === "running" || st?.trial.state === "running";
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => { void load(); }, 1500);
    return () => window.clearInterval(t);
  }, [running, load]);

  const act = async <T,>(fn: () => Promise<T>, done?: string | ((result: T) => string)) => {
    setBusy(true);
    try {
      const result = await fn();
      await load();
      const text = typeof done === "function" ? done(result) : done;
      if (text) toast(text);
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
  const cloud = c.mode === "remote" ? c.remote : null;
  const comfyReady = c.mode === "clipforge" ? c.installed : c.mode === "app" ? Boolean(c.app_found)
    : c.mode === "remote" ? Boolean(cloud?.found) : false;
  const cloudName = cloud ? cloud.gpu || cloud.host || "your cloud computer" : "";

  // the reasons name this page for other pages (the shorts maker); here that hint is redundant
  const why = (role: EngineRole) => st.roles[role].why.replace(/ \(Settings, Pictures, video, voice\)/, "");

  const fitNote = (m: EngineModel) => {
    if (cloud) {  // the fit is the cloud computer's (its graphics card), not this one's
      if (m.fit === "slow") return `Your cloud computer's graphics card has ${Math.round((cloud.vram_mb || 0) / 1024)} GB, so this one will be slow there. Rent one with at least ${m.vram_gb} GB.`;
      if (m.fit === "cpu") return "Your cloud computer has no graphics card ComfyUI can use, so this would be very slow there.";
      return "";
    }
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
      <li key={m.id} className="file-row maker-row"><Icon name={m.role === "image" ? "spark" : m.role === "video" ? "film" : "play"} />
        <div><b>{m.name}</b> <span className="small muted">by {m.maker} · <a href={m.licence_url} target="_blank"
          rel="noreferrer">{m.licence}</a></span>
          <span className="block small">{m.about}</span>
          {cloud && m.role !== "voice" ? <span className="block small muted">{m.ready ? "On your cloud computer"
            : `Not on it yet: ${gb(m.download_bytes || m.bytes)}`}{m.vram_gb ? ` · runs well on a graphics card with ${m.vram_gb} GB` : ""}</span>
            : <span className="block small muted">{m.ready ? "Downloaded" : `Download: ${gb(m.download_bytes || m.bytes)}`}
            {m.memory_gb ? ` · runs well on a Mac with ${m.memory_gb} GB of memory or a PC with an NVIDIA card with ${m.vram_gb} GB` : ""}</span>}
          {fitNote(m) && <span className="block small">{fitNote(m)}</span>}</div>
        {m.ready ? <Pill tone="good" icon="check">{chosen && byRole(m.role).length > 1 ? "In use" : "Ready"}</Pill>
          : m.removable ? <Pill tone="warn">Partly downloaded</Pill>
          : cloud && m.role !== "voice" ? (m.recommended ? <Pill tone="info">Best for your cloud computer</Pill> : <Pill>Not on it yet</Pill>)
          : m.recommended ? <Pill tone="info">Best for this computer</Pill> : <Pill>Not downloaded</Pill>}
        <div className="row-actions">
          {m.ready && byRole(m.role).length > 1 && !chosen && <button type="button" className="btn btn-small" disabled={busy}
            onClick={() => void save({ [m.role === "image" ? "engines_picture" : m.role === "video" ? "engines_video" : "engines_voice"]: m.id })}>
            Use this</button>}
          {!m.ready && m.can_download && <button type="button" className="btn btn-small" disabled={busy || setupRunning ||
            (m.role !== "voice" && !comfyReady)} onClick={() => setConfirm({ what: "model", model: m })}>
            <Icon name="download" />Download</button>}
          {cloud && m.role !== "voice" && !m.ready && <button type="button" className="btn btn-small" disabled={busy || !cloud.found}
            title={cloud.found ? undefined : "Connect your cloud computer above first."} onClick={() => openCommand(m)}>
            <Icon name="download" />Put it on your cloud computer</button>}
          {m.removable && <button type="button" className="btn btn-small btn-quiet" disabled={busy || setupRunning}
            onClick={() => void act(() => engines.remove("model", m.id), (v) => v.note || `${m.name} removed.`)}>
            <Icon name="trash" />Remove</button>}
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

  // ------------------------------------------------------------------ the cloud computer
  const connect = (key?: string) => act(() => engines.connectCloud(cloudUrl.trim() || cloud?.url || "", key), (v) => {
    const r = v.comfyui.remote;
    if (r.url) setCloudUrl(r.url);
    const said = r.found ? `Connected to your cloud computer${r.gpu ? ` (${r.gpu})` : ""}.` : "Saved. It did not answer yet: see below.";
    return v.note ? `${said} ${v.note}` : said;
  });

  const fetchCommand = async (m: EngineModel, agreed: boolean) => {
    setCommand({ model: m, view: null, error: "" });
    try {
      setCommand({ model: m, view: await engines.cloudCommand(m.id, agreed), error: "" });
    } catch (e) {
      setCommand({ model: m, view: null, error: errorText(e) });
    }
  };
  // a model with use rules shows them first; pressing "Agree and show the command" is agreeing to them
  const openCommand = (m: EngineModel) => {
    if (m.rule) setCommand({ model: m, view: null, error: "" });
    else void fetchCommand(m, false);
  };
  const copyCommand = async (text: string) => {
    try { await navigator.clipboard.writeText(text); toast("Command copied. Paste it into your cloud computer's terminal."); }
    catch { toast("Could not copy. Select the command and copy it yourself.", true); }
  };
  const checkCommand = async (m: EngineModel) => {
    setBusy(true);
    try {
      const v = await engines.connectCloud(cloud?.url || cloudUrl.trim());
      setSt(v);
      const now = v.models.find((x) => x.id === m.id);
      if (now?.ready) {
        setCommand(null);
        toast(`${m.name} is on your cloud computer.`);
      } else {
        toast(v.comfyui.remote.found ? `${m.name} is not all there yet. Wait until the command says Done, then check again.`
          : v.comfyui.remote.why || "Your cloud computer did not answer.", true);
      }
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
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
        <p className="small muted">Made {cloud && role !== "voice" ? "on your cloud computer" : "on this computer"} in {trial.seconds} seconds.</p>
      </div>
    );
  };

  return (
    <>
      <section className="panel" aria-labelledby="lm-what"><h2 id="lm-what">{cloud ? "Pictures, video and voice"
        : "Pictures, video and voice on this computer"}</h2>
        {cloud ? <p className="small">ClipForge makes pictures and short video clips on the cloud computer you rent, which is
          much faster than most computers, and the voice-overs here, inside ClipForge: the animated-shorts maker uses them.
          Pictures and clips are made by ComfyUI, a free, open-source program, with models whose licences allow commercial
          use. The cloud computer gets the words for each picture or clip (and the picture a clip starts from) and sends
          back what it made.</p>
          : <p className="small">ClipForge can make pictures, short video clips and voice-overs itself, on this computer, for free:
          the animated-shorts maker uses them. Pictures and clips are made by ComfyUI, a free, open-source
          program, with models whose licences allow commercial use. The voice runs inside ClipForge. Once downloaded,
          nothing goes online and nothing you make leaves the computer.</p>}
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
            { value: "remote", label: "A cloud computer" },
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
        {cloud && <>
          <p className="small muted">Rent a computer with a fast graphics card by the hour (RunPod is one place that does
            this), start ComfyUI on it, and paste its address here. ClipForge sends it the words for each picture or clip,
            and the picture a clip starts from, and gets back what it made. The voice still runs on this computer.</p>
          <p className="small">{cloud.found ? <><Pill tone="good" icon="check">Connected</Pill> {cloudName}
            {cloud.version ? ` · ComfyUI ${cloud.version}` : ""}{cloud.vram_mb ? ` · ${Math.round(cloud.vram_mb / 1024)} GB of graphics memory` : ""}</>
            : <><Pill>{cloud.url ? "Not answering" : "Not connected"}</Pill> {cloud.url ? cloud.why : "Follow the steps below, then paste its address."}</>}</p>
          {cloud.found && <Banner tone="warn" title="It costs money every hour it is on">Your cloud computer costs money for
            every hour it is on, even when ClipForge is not using it. When you finish, open RunPod and press Stop on your pod.
            Start it again next time (its address stays the same).</Banner>}
          <div className="row-actions" style={{ alignItems: "flex-end" }}>
            <label className="field grow"><span>Your cloud computer&apos;s address</span><input value={cloudUrl}
              placeholder="https://abc123xyz-8188.proxy.runpod.net" spellCheck={false} autoComplete="off"
              onChange={(e) => setCloudUrl(e.target.value)} /></label>
            <button type="button" className="btn btn-small" disabled={busy || !cloudUrl.trim()} onClick={() => void connect()}>
              Save and check</button>
            <button type="button" className="btn btn-small btn-quiet" disabled={busy || !cloud.url}
              onClick={() => void act(() => engines.connectCloud(cloud.url))}><Icon name="refresh" />Check again</button>
          </div>
          <Disclosure summary={cloud.key_set ? "Key: kept on this computer" : "Does it need a password? (Most don't.)"}>
            <p className="small">Only if you put a password in front of your ComfyUI yourself. ClipForge keeps it locked on this
              computer and sends it only to the address above. For a user name and a password, type them as
              {" "}<span className="mono">name:password</span>.</p>
            <div className="row-actions" style={{ alignItems: "flex-end" }}>
              <label className="field grow"><span>{cloud.key_set ? "A new key" : "Key or password"}</span>
                <input type="password" value={cloudKey} autoComplete="off" onChange={(e) => setCloudKey(e.target.value)} /></label>
              <button type="button" className="btn btn-small" disabled={busy || !cloudKey.trim() || !(cloudUrl.trim() || cloud.url)}
                onClick={() => void connect(cloudKey.trim()).then(() => setCloudKey(""))}>Save key</button>
              {cloud.key_set && <button type="button" className="btn btn-small btn-quiet" disabled={busy || !(cloudUrl.trim() || cloud.url)}
                onClick={() => void connect("")}><Icon name="trash" />Remove key</button>}
            </div>
          </Disclosure>
          <Disclosure summary="How to get a cloud computer on RunPod, step by step" open={!cloud.url}>
            <ol className="steps-list">
              <li>Go to <a href="https://www.runpod.io" target="_blank" rel="noreferrer">runpod.io</a> and make an account.
                In Billing, add some credit ($10 is plenty to try it).</li>
              <li>Press <b>Pods</b>, then <b>Deploy</b>. Choose <b>Community Cloud</b> (it is cheaper).</li>
              <li>Pick an <b>RTX 5090</b>: it is the fastest. An <b>RTX 4090</b> costs less and works well too. Any card with
                at least 24 GB is fine. RunPod shows the price per hour next to each one.</li>
              <li>Press <b>Change Template</b>. For an RTX 5090 pick <b>ComfyUI Blackwell Edition</b>. For an RTX 4090 pick
                {" "}<b>ComfyUI</b>.</li>
              <li>Press <b>Edit Template</b> and set the <b>Volume Disk</b> to <b>100 GB</b>, so the models fit and stay there.
                Save it.</li>
              <li>Press <b>Deploy On-Demand</b>. Wait until your pod says <b>Running</b> (a few minutes the first time).</li>
              <li>Press <b>Connect</b>, then the button for port <b>8188</b>. ComfyUI opens in a new tab. Copy that tab&apos;s
                address from the top of your browser. It looks like <span className="mono">https://abc123xyz-8188.proxy.runpod.net</span>.</li>
              <li>Paste it in the box above and press <b>Save and check</b>.</li>
              <li>Put the models on it: in Pictures and in Video clips below, press <b>Put it on your cloud computer</b> and
                follow the steps.</li>
              <li>When you finish, press <b>Stop</b> on your pod in RunPod. It stops costing money for the graphics card.
                Its 100 GB disk still costs a little while it is stopped (about $20 a month). If you will not use it for a
                long time, press <b>Terminate</b> instead: that costs nothing, but the models are deleted and you put them
                back next time.</li>
            </ol>
            <p className="small">Keep the address to yourself: anyone who has it can use your cloud computer while it is on.</p>
          </Disclosure>
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
          {c.mode !== "off" && !comfyReady && <p className="small muted">{cloud ? "Connect your cloud computer above first."
            : "Set up ComfyUI above first."}</p>}
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
            its licence, the words and the seed. What an animated short uses is kept with that short instead, with its
            note, and goes when the short is deleted.</li>
          {cloud && <li>On your cloud computer: the models are in ComfyUI&apos;s models folder there. ComfyUI also keeps a copy
            of each picture and clip it made, and of each picture a clip started from, in its output and input folders
            there, until you delete them or terminate the pod. ClipForge keeps what it gets back in engines/made here.</li>}
          <li>ComfyUI {c.version} is GPL-3.0 open source (<a href={c.source} target="_blank" rel="noreferrer">its source</a>). It
            runs as a separate program that ClipForge talks to on this computer only.</li>
          <li>Each model, the voice and ComfyUI itself have a fixed address, size and checksum: a file that does not match
            is deleted and never used. The parts ComfyUI runs on (its Python, PyTorch and their packages) are fixed
            versions that uv checks as it downloads them.</li>
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

      {command && <Dialog wide title={`Put ${command.model.name} on your cloud computer`} onClose={() => setCommand(null)}
        actions={command.view?.command ? <>
          <button type="button" className="btn btn-quiet" onClick={() => setCommand(null)}>Close</button>
          <button type="button" className="btn" onClick={() => void copyCommand(command.view?.command || "")}><Icon name="copy" />Copy the command</button>
          <button type="button" className="btn" disabled={busy} onClick={() => void checkCommand(command.model)}>
            <Icon name="refresh" />I ran it: check again</button>
        </> : !command.view && !command.error && command.model.rule ? <>
          <button type="button" className="btn btn-quiet" onClick={() => setCommand(null)}>Cancel</button>
          <button type="button" className="btn" onClick={() => void fetchCommand(command.model, true)}>Agree and show the command</button>
        </> : <button type="button" className="btn" onClick={() => setCommand(null)}>Close</button>}>
        {command.error ? <Banner tone="bad" title="No command">{command.error}</Banner>
          : !command.view && command.model.rule ? <>
            <p>{command.model.about} {command.model.name} is made by {command.model.maker} and comes under
              {" "}<a href={command.model.licence_url} target="_blank" rel="noreferrer">{command.model.licence}</a>.</p>
            <p><b>Its use rules:</b> {command.model.rule}</p>
          </>
          : !command.view ? <p className="small muted">Asking your cloud computer what it has…</p>
          : !command.view.command ? <p>Your cloud computer already has everything {command.view.name} needs. Press Close, then
            Check again at the top.</p>
          : <>
            <ol className="steps-list">
              <li>In RunPod, press <b>Connect</b> on your pod. Turn on the <b>Web Terminal</b> and open it (or open
                {" "}<b>JupyterLab</b>, then File, New, Terminal).</li>
              <li>Press <b>Copy the command</b> below. Click in the terminal, paste it, and press Enter.</li>
              <li>Wait until it says <b>Done</b>. It downloads {gb(command.view.bytes)} on the cloud computer, which usually
                takes a few minutes, sometimes longer. Your own internet is not used.</li>
              <li>Come back here and press <b>I ran it: check again</b>.</li>
            </ol>
            {!command.view.asked && <Banner tone="info" title="Your cloud computer did not answer just now">The command finds
              ComfyUI&apos;s models folder by itself. {command.view.why}</Banner>}
            <pre className="command-box" aria-label="The command">{command.view.command}</pre>
            <p className="small muted">{command.view.files.length === 1 ? "1 file" : `${command.view.files.length} files`}
              {command.view.where ? ` go into ${command.view.where}` : ""}. Each one is checked when it arrives; a damaged
              one is deleted. If it stops, paste the same command again: it goes on where it stopped.</p>
          </>}
      </Dialog>}
    </>
  );
}
