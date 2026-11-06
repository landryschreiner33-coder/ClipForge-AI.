import { useCallback, useEffect, useState } from "react";
import { AiPreset, AiSetup, api, BuiltinAi, errorText, Settings } from "../api";
import { Banner, Disclosure, Icon, LoadingPage, Pill, ProgressBar, toast } from "./ui";

const SAVED = "********";
const trim = (u: unknown) => String(u || "").replace(/\/+$/, "").toLowerCase();

/** Which ready-made choice the saved settings are (or "" for none / one typed by hand). */
function currentPreset(s: Settings, presets: AiPreset[]): string {
  if (s.ai_provider === "builtin") return "builtin";
  if (s.ai_provider === "ollama") return "ollama";
  if (s.ai_provider === "anthropic") return "anthropic";
  if (s.ai_provider === "openai_compatible") {
    const p = presets.find((x) => x.provider === "openai_compatible" && trim(x.url) === trim(s.openai_url));
    return p ? p.id : "custom";
  }
  return "";
}

/**
 * Settings → ClipForge AI: pick the model ClipForge AI uses (the built-in one on this computer, Ollama, LM Studio or a
 * free key) for smart editing, clip scoring, its chat and the changes you ask for. Each choice is saved and tested in one step; a key is only ever sent
 * to the service it belongs to.
 */
export default function AiHelperSettings() {
  const [setup, setSetup] = useState<AiSetup | null>(null);
  const [s, setS] = useState<Settings | null>(null);
  const [problem, setProblem] = useState("");
  const [pick, setPick] = useState("");
  const [key, setKey] = useState("");
  const [model, setModel] = useState("");
  const [url, setUrl] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);
  const [gguf, setGguf] = useState({ path: "", name: "" });

  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([api.aiSetup(), api.settings()]);
      setSetup(a);
      setS(b);
      setProblem("");
      return { a, b };
    } catch (e) {
      setProblem(errorText(e));
      return null;
    }
  }, []);
  useEffect(() => {
    void load().then((r) => {
      if (!r) return;
      const id = currentPreset(r.b, r.a.presets) || "builtin";
      choose(id, r.a, r.b);
    });
  }, [load]); // eslint-disable-line react-hooks/exhaustive-deps
  // A download or import runs in the background: follow it.
  const running = setup?.task?.state === "running" || setup?.builtin?.task?.state === "running";
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => {
      void api.aiSetup().then((a) => {
        setSetup(a);
        // The built-in model becomes ClipForge AI's model when its download finishes (unless another one was chosen).
        if (a.builtin?.task?.state !== "running") void api.settings().then(setS).catch(() => undefined);
      }).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(t);
  }, [running]);

  function choose(id: string, a = setup, b = s) {
    if (!a || !b) return;
    setPick(id);
    setKey("");
    setResult(null);
    setModels([]);
    const p = a.presets.find((x) => x.id === id);
    const same = currentPreset(b, a.presets) === id;
    if (id === "ollama") {
      setUrl(String(b.ollama_url || p?.url || ""));
      setModel(String((same && b.ollama_model) || a.recommended || p?.model || ""));
    } else if (id === "anthropic") {
      setUrl("");
      setModel(String((same && b.anthropic_model) || p?.model || ""));
    } else {
      setUrl(String(same ? b.openai_url : p?.url || ""));
      setModel(String(same ? b.openai_model || "" : p?.model || ""));
    }
  }

  if (problem && !setup) return <Banner tone="bad" title="ClipForge AI's settings could not be loaded">{problem}</Banner>;
  if (!setup || !s) return <LoadingPage label="Loading ClipForge AI's settings" />;
  const preset = setup.presets.find((p) => p.id === pick);
  const now = currentPreset(s, setup.presets);
  const on = s.ai_provider && s.ai_provider !== "heuristic";
  const keySaved = (k: string) => s[k] === SAVED;
  const installed = setup.ollama.models.map((m) => m.name);

  /** Save this choice and test it (the test uses the saved settings). */
  const useIt = async (override?: string) => {
    if (!preset) return;
    const m = (override ?? model).trim();
    let patch: Settings;
    if (preset.provider === "ollama") {
      patch = { ai_provider: "ollama", ollama_url: url.trim() || preset.url, ollama_model: m || setup.recommended };
    } else if (preset.provider === "anthropic") {
      if (!key && !keySaved("anthropic_api_key")) { toast("Paste your Claude API key first.", true); return; }
      patch = { ai_provider: "anthropic", anthropic_model: m || preset.model, ...(key ? { anthropic_api_key: key.trim() } : {}) };
    } else {
      const target = url.trim() || preset.url;
      // A saved key belongs to the address it was saved for: switching services never sends it to the new one.
      const moved = trim(target) !== trim(s.openai_url);
      if (preset.needs_key && !key && (moved || !keySaved("openai_api_key"))) { toast(`Paste your ${preset.name} key first.`, true); return; }
      patch = { ai_provider: "openai_compatible", openai_url: target, openai_model: m,
        ...(key ? { openai_api_key: key.trim() } : moved ? { openai_api_key: "" } : {}) };
    }
    setBusy(true);
    setResult(null);
    try {
      await api.saveSettings(patch);
      setKey("");
      const r = await api.checkAi();
      let list = r.models || [];
      if (preset.id === "openrouter") list = list.filter((x) => x.endsWith(":free"));
      setModels(list);
      // OpenRouter: only ":free" models cost nothing, so one is picked when none was chosen.
      if (preset.id === "openrouter" && list.length && !list.includes(m)) {
        await api.saveSettings({ openai_model: list[0] });
        setModel(list[0]);
        const again = await api.checkAi();
        setResult({ ok: again.ok, detail: again.detail });
      } else {
        setResult({ ok: r.ok, detail: r.detail });
      }
      await load();
    } catch (e) {
      setResult({ ok: false, detail: errorText(e) });
    }
    setBusy(false);
  };
  const turnOff = async () => {
    setBusy(true);
    try {
      await api.saveSettings({ ai_provider: "heuristic" });
      await load();
      toast("ClipForge AI has no model now. ClipForge's built-in editor decides alone; the chat still remembers and explains.");
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
  };
  const download = async (name: string) => {
    try {
      setSetup({ ...setup, task: await api.ollamaPull(name) });
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const importFile = async () => {
    try {
      setSetup({ ...setup, task: await api.ollamaImport(gguf.path, gguf.name) });
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const task = setup.task || {};
  const progress = task.total ? (task.completed || 0) / task.total : 0;

  return (
    <div className="stack-4">
      <section className="panel" aria-labelledby="ai-now">
        <h2 id="ai-now">ClipForge AI</h2>
        <p>ClipForge AI is the editor's assistant: it remembers what you tell it (Brain → Memory), proposes the changes you
          ask for on a video, and answers questions (Brain → Talk). It needs a model to read and write. Without one, ClipForge
          still edits your videos and ClipForge AI still remembers, forgets, lists and explains. With one it also reads what is
          said (as text, never the video or the sound) to choose better cuts, pictures and chapters, scores clips, understands
          more of what you ask, and answers questions. The built-in model comes with ClipForge and runs on this computer.
          Every choice here is free except the Claude API.</p>
        <div className="row wrap">
          <Pill tone={on ? "good" : "neutral"} icon={on ? "check" : "info"}>{on ? `Using ${setup.label}` : "No model: built-in editor only"}</Pill>
          {on && <button type="button" className="btn btn-small" disabled={busy} onClick={turnOff}>Turn off</button>}
        </div>
      </section>

      <section className="panel" aria-labelledby="ai-pick">
        <h2 id="ai-pick">Choose its model</h2>
        <div className="mode-pick" role="radiogroup" aria-label="ClipForge AI's model">
          {setup.presets.map((p) => (
            <label key={p.id}><input type="radio" name="ai-preset" checked={pick === p.id} onChange={() => choose(p.id)} />
              <b>{p.name}{now === p.id && on ? " (in use)" : ""}</b><span>{p.cost}{p.local ? " · on this computer" : " · online"}</span></label>
          ))}
        </div>
        {preset && <div className="stack-3">
          <p className="small">{preset.about} {preset.key_url && <a className="textlink" href={preset.key_url} target="_blank" rel="noreferrer">
            {preset.provider === "ollama" ? "Get Ollama" : preset.local ? "Get LM Studio" : preset.needs_key ? "Get a key" : "Website"}<Icon name="external" className="sm" /></a>}</p>
          {!preset.local && preset.id !== "anthropic" && <p className="small muted">Free tiers have daily limits set by the service. When one is used up, ClipForge's built-in editor carries on alone.</p>}

          {preset.provider === "builtin" && <BuiltinSetup b={setup.builtin} inUse={now === "builtin" && !!on}
            onChange={async () => { await load(); }} />}

          {preset.provider === "ollama" && <>
            {setup.ollama.running
              ? <p className="small"><Icon name="check" className="sm" /> Ollama {setup.ollama.version} is running{installed.length ? ` with ${installed.length} model${installed.length === 1 ? "" : "s"}` : ", with no models yet"}.</p>
              : <Banner tone="warn" title="Ollama is not running" actions={<button type="button" className="btn btn-small" onClick={() => void load()}><Icon name="refresh" />Check again</button>}>
                {setup.ollama.problem}</Banner>}
            <label className="field"><span>Model</span>
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                {installed.map((n) => <option key={n} value={n}>{n} (downloaded)</option>)}
                {setup.ollama_models.filter((m) => !installed.includes(m.name)).map((m) => (
                  <option key={m.name} value={m.name}>{m.name}, {m.size_gb} GB download{m.name === setup.recommended ? " (recommended here)" : ""}</option>))}
                {model && !installed.includes(model) && !setup.ollama_models.some((m) => m.name === model) && <option value={model}>{model}</option>}
              </select></label>
            {setup.ollama.running && model && !installed.includes(model) && (
              <div className="row wrap">
                <button type="button" className="btn" disabled={running} onClick={() => void download(model)}><Icon name="download" />Download {model}</button>
                <span className="small muted">{setup.ollama_models.find((m) => m.name === model)?.about}</span>
              </div>)}
            {task.state && (
              <div className="stack-2" aria-live="polite">
                <b className="small">{task.kind === "import" ? "Importing" : "Downloading"} {task.model}: {task.state === "failed" ? task.error : task.status}</b>
                {task.state === "running" && <ProgressBar value={progress} label="Progress" />}
              </div>)}
            <Disclosure summary="Use a model file you already have (.gguf)">
              <div className="stack-3">
                <p className="small muted">Adds a .gguf model file on this computer to Ollama (it is copied into Ollama's folder). Small instruction-tuned models of 3 to 8 billion parameters work best.</p>
                <label className="field"><span>File path</span><input value={gguf.path} placeholder="For example C:\Models\my-model.gguf or ~/Models/my-model.gguf" onChange={(e) => setGguf({ ...gguf, path: e.target.value })} /></label>
                <label className="field"><span>Name in Ollama</span><input value={gguf.name} placeholder="my-model" maxLength={60} onChange={(e) => setGguf({ ...gguf, name: e.target.value.toLowerCase() })} /></label>
                <button type="button" className="btn" disabled={running || !gguf.path || !gguf.name || !setup.ollama.running} onClick={importFile}><Icon name="upload" />Import</button>
                {task.kind === "import" && task.state === "done" && <button type="button" className="btn btn-small" onClick={() => { setModel(gguf.name); void useIt(gguf.name); }}>Use {gguf.name}</button>}
              </div>
            </Disclosure>
            <Disclosure summary="Ollama address">
              <label className="field"><span>Address</span><input value={url} onChange={(e) => setUrl(e.target.value)} /></label>
            </Disclosure>
          </>}

          {preset.provider === "openai_compatible" && <>
            {preset.local && <label className="field"><span>Server address</span><input value={url} onChange={(e) => setUrl(e.target.value)} /></label>}
            {preset.needs_key && <label className="field"><span>{preset.name} key</span>
              <input type="password" autoComplete="off" value={key} placeholder={trim(url || preset.url) === trim(s.openai_url) && keySaved("openai_api_key") ? "•••••••• (saved; paste to replace)" : "Paste your key"}
                onChange={(e) => setKey(e.target.value)} /></label>}
            <label className="field"><span>Model</span>
              {models.length ? <select value={model} onChange={(e) => setModel(e.target.value)}>
                {!models.includes(model) && <option value={model}>{model || "Choose a model"}</option>}
                {models.map((m) => <option key={m} value={m}>{m}</option>)}</select>
                : <input value={model} placeholder={preset.id === "openrouter" ? "Picked for you (a free model)" : preset.local ? "Loaded after Use this" : ""} onChange={(e) => setModel(e.target.value)} />}</label>
          </>}

          {preset.provider === "anthropic" && <>
            <label className="field"><span>Claude API key</span>
              <input type="password" autoComplete="off" value={key} placeholder={keySaved("anthropic_api_key") ? "•••••••• (saved; paste to replace)" : "sk-ant-…"} onChange={(e) => setKey(e.target.value)} /></label>
            <label className="field"><span>Model</span><input value={model} onChange={(e) => setModel(e.target.value)} /></label>
          </>}

          {preset.provider !== "builtin" && <div className="row wrap">
            <button type="button" className="btn btn-primary" disabled={busy || (preset.provider === "ollama" && !setup.ollama.running)} onClick={() => void useIt()}>
              {busy ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="check" />}{now === pick && on ? "Save and test" : "Use this"}</button>
            {result && <Pill tone={result.ok ? "good" : "bad"} icon={result.ok ? "check" : "alert"}>{result.detail}</Pill>}
          </div>}
        </div>}
        {now === "custom" && <p className="small muted">You use your own server ({String(s.openai_url)}); its settings are on <a className="textlink" href="#/settings/advanced">Advanced</a>. Choosing one above replaces it.</p>}
      </section>
    </div>
  );
}

const gb = (bytes: number) => `${(bytes / 1e9).toFixed(1)} GB`;

/**
 * The built-in model: pick a level (the one that fits this computer is preselected), download it once, and it becomes
 * ClipForge AI's model. The engine (llama.cpp) and the model run on this computer only; nothing is sent anywhere.
 */
function BuiltinSetup({ b, inUse, onChange }: { b: BuiltinAi; inUse: boolean; onChange: () => Promise<void> }) {
  const [level, setLevel] = useState(b.level || b.recommended);
  const [busy, setBusy] = useState(false);
  if (!b.supported) {
    return <Banner tone="warn" title="Not available on this computer">The built-in model needs a Mac with Apple silicon, or a
      64-bit Windows or Linux PC. Ollama or a free online key below still work.</Banner>;
  }
  const t = b.task || {};
  const running = t.state === "running";
  const pick = b.levels.find((l) => l.id === level) || b.levels[0];
  const mem = b.computer.memory_mb ? `${Math.round(b.computer.memory_mb / 1024)} GB of memory` : "memory unknown";
  const gpu = b.computer.mac ? "Apple silicon" : b.computer.vram_mb ? `a graphics card with ${Math.round(b.computer.vram_mb / 1024)} GB` : "no NVIDIA graphics card found";
  const act = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    try {
      await fn();
      await onChange();
      if (done) toast(done);
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
  };
  return (
    <div className="stack-3">
      <p className="small">This computer: {mem}, {gpu}. {b.levels.find((l) => l.recommended)?.name} fits it best.</p>
      <div className="mode-pick" role="radiogroup" aria-label="Built-in model level">
        {b.levels.map((l) => (
          <label key={l.id}><input type="radio" name="builtin-level" checked={level === l.id} onChange={() => setLevel(l.id)} />
            <b>{l.name}: {l.model}{l.recommended ? " (recommended here)" : ""}{l.installed ? " · downloaded" : ""}</b>
            <span>{l.about} {l.installed ? "" : `${gb(l.download_bytes)} download, once.`}{!l.fits ? " Needs more memory than this computer has; it may be very slow." : ""}</span></label>
        ))}
      </div>
      {running ? (
        <div className="stack-2" aria-live="polite">
          <b className="small">{t.status || "Starting"}{t.total ? `: ${gb(t.completed || 0)} of ${gb(t.total)}` : ""}</b>
          <ProgressBar value={t.total ? (t.completed || 0) / t.total : 0} label="Setting up the built-in model" />
          <div className="row wrap"><button type="button" className="btn btn-small" onClick={() => void act(() => api.builtinCancel())}>Cancel</button>
            <span className="small muted">You can keep working; a stopped download resumes where it stopped.</span></div>
        </div>
      ) : (
        <div className="row wrap">
          {pick.installed
            ? <button type="button" className="btn btn-primary" disabled={busy || (inUse && b.level === pick.id)}
                onClick={() => void act(() => api.builtinUse(pick.id), `Using the built-in model (${pick.model}).`)}>
                <Icon name="check" />{inUse && b.level === pick.id ? "In use" : "Use this"}</button>
            : <button type="button" className="btn btn-primary" disabled={busy}
                onClick={() => void act(() => api.builtinInstall(pick.id))}>
                <Icon name="download" />Download {pick.name} ({gb(pick.download_bytes)})</button>}
          {t.state === "failed" && <Pill tone="bad" icon="alert">{t.error}</Pill>}
          {t.state === "done" && <Pill tone="good" icon="check">Ready</Pill>}
        </div>
      )}
      {b.server.running && <p className="small muted">Running now ({b.levels.find((l) => l.id === b.server.level)?.model}); it stops after {b.server.idle_minutes} minutes without work so the memory goes back to your videos.</p>}
      <Disclosure summary="What gets downloaded">
        <div className="stack-2 small">
          <p>The engine is llama.cpp ({b.engine.license}), release {b.engine.version}. The models are {Array.from(new Set(b.levels.map((l) => l.license))).join(", ")} licensed.
            Every file is checked against a fixed checksum before it is used, and the engine only listens on this computer.</p>
          {b.levels.filter((l) => l.installed).map((l) => (
            <div key={l.id} className="row wrap"><span>{l.name} ({l.model}) is downloaded.</span>
              <button type="button" className="btn btn-small" disabled={busy || running}
                onClick={() => void act(() => api.builtinRemove(l.id), `${l.name} was removed. Download it again any time.`)}>Remove to free {gb(l.download_bytes)}</button></div>
          ))}
        </div>
      </Disclosure>
    </div>
  );
}
