import { useCallback, useEffect, useState } from "react";
import { AiPreset, AiSetup, api, errorText, Settings } from "../api";
import { Banner, Disclosure, Icon, LoadingPage, Pill, ProgressBar, toast } from "./ui";

const SAVED = "********";
const trim = (u: unknown) => String(u || "").replace(/\/+$/, "").toLowerCase();

/** Which ready-made choice the saved settings are (or "" for none / one typed by hand). */
function currentPreset(s: Settings, presets: AiPreset[]): string {
  if (s.ai_provider === "ollama") return "ollama";
  if (s.ai_provider === "anthropic") return "anthropic";
  if (s.ai_provider === "openai_compatible") {
    const p = presets.find((x) => x.provider === "openai_compatible" && trim(x.url) === trim(s.openai_url));
    return p ? p.id : "custom";
  }
  return "";
}

/**
 * Settings → AI helper: pick a free AI service (a model on this computer, or a free key) for smart editing, clip
 * scoring and "Tell the editor what to change". Each choice is saved and tested in one step; a key is only ever sent
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
      const id = currentPreset(r.b, r.a.presets) || "ollama";
      choose(id, r.a, r.b);
    });
  }, [load]); // eslint-disable-line react-hooks/exhaustive-deps
  // A download or import runs in the background: follow it.
  const running = setup?.task?.state === "running";
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => { void api.aiSetup().then(setSetup).catch(() => undefined); }, 1500);
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

  if (problem && !setup) return <Banner tone="bad" title="The AI helper settings could not be loaded">{problem}</Banner>;
  if (!setup || !s) return <LoadingPage label="Loading the AI helper" />;
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
      toast("The AI helper is off. ClipForge's built-in editor decides alone.");
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
        <h2 id="ai-now">AI helper</h2>
        <p>Optional. ClipForge edits your videos without one. With an AI helper it also reads what is said (as text, never the
          video or the sound) to choose better cuts, pictures and chapters, scores clips, and understands more of what you
          type in “Tell the editor what to change”. Every choice here is free except the Claude API.</p>
        <div className="row wrap">
          <Pill tone={on ? "good" : "neutral"} icon={on ? "check" : "info"}>{on ? `Using ${setup.label}` : "Off: built-in editor only"}</Pill>
          {on && <button type="button" className="btn btn-small" disabled={busy} onClick={turnOff}>Turn off</button>}
        </div>
      </section>

      <section className="panel" aria-labelledby="ai-pick">
        <h2 id="ai-pick">Choose one</h2>
        <div className="mode-pick" role="radiogroup" aria-label="AI helper">
          {setup.presets.map((p) => (
            <label key={p.id}><input type="radio" name="ai-preset" checked={pick === p.id} onChange={() => choose(p.id)} />
              <b>{p.name}{now === p.id && on ? " (in use)" : ""}</b><span>{p.cost}{p.local ? " · on this computer" : " · online"}</span></label>
          ))}
        </div>
        {preset && <div className="stack-3">
          <p className="small">{preset.about} {preset.key_url && <a className="textlink" href={preset.key_url} target="_blank" rel="noreferrer">
            {preset.provider === "ollama" ? "Get Ollama" : preset.local ? "Get LM Studio" : preset.needs_key ? "Get a key" : "Website"}<Icon name="external" className="sm" /></a>}</p>
          {!preset.local && preset.id !== "anthropic" && <p className="small muted">Free tiers have daily limits set by the service. When one is used up, ClipForge's built-in editor carries on alone.</p>}

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

          <div className="row wrap">
            <button type="button" className="btn btn-primary" disabled={busy || (preset.provider === "ollama" && !setup.ollama.running)} onClick={() => void useIt()}>
              {busy ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="check" />}{now === pick && on ? "Save and test" : "Use this"}</button>
            {result && <Pill tone={result.ok ? "good" : "bad"} icon={result.ok ? "check" : "alert"}>{result.detail}</Pill>}
          </div>
        </div>}
        {now === "custom" && <p className="small muted">You use your own server ({String(s.openai_url)}); its settings are on <a className="textlink" href="#/settings/advanced">Advanced</a>. Choosing one above replaces it.</p>}
      </section>
    </div>
  );
}
