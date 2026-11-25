/**
 * Settings → Processing (docs/clipforge/FULL_CLOUD.md): where Make clips runs (Local, Hybrid or Full Cloud), the
 * owner's ClipForge worker (address, key, check), worker time with the owner's price and monthly limit, and the
 * private test job that proves each stage runs on the worker.
 */
import { useCallback, useEffect, useState } from "react";
import { errorText } from "../api";
import { fmtBytes, fmtMoney, fmtSpan, Processing, processing, ProcessingMode, STAGE_NAMES, WorkerTest } from "../processing";
import { Banner, Disclosure, Icon, Pill, ProgressBar, toast } from "./ui";

export default function ProcessingSettings() {
  const [p, setP] = useState<Processing | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [price, setPrice] = useState("");
  const [hours, setHours] = useState("");

  // the price and limit fields show the saved values, except while the owner is typing new ones (`fields`)
  const take = useCallback((got: Processing, fields = true) => {
    setP(got);
    if (!fields) return;
    setPrice(got.price_per_hour ? String(got.price_per_hour) : "");
    setHours(String(got.month_hours ?? 0));
  }, []);
  const load = useCallback(async (check = false, fields = true) => {
    try {
      const got = await processing.get(check);
      take(got, fields);
      setUrl((u) => u || got.worker.url);
      setProblem("");
    } catch (e) {
      setProblem(errorText(e));
    }
  }, [take]);
  useEffect(() => { void load(true); }, [load]);

  const testRunning = !!p?.test?.job && ["queued", "running"].includes(p.test.job.status);
  useEffect(() => {  // follow the test job while it runs
    if (!testRunning) return;
    const t = window.setInterval(() => { void load(false, false); }, 1500);
    return () => window.clearInterval(t);
  }, [testRunning, load]);

  /** Runs one change; true when it worked (a typed key or address is cleared only then). */
  const act = async (fn: () => Promise<Processing | void>, done?: string): Promise<boolean> => {
    setBusy(true);
    try {
      const got = await fn();
      if (got) take(got);
      if (got && got.note) toast(got.note);
      else if (done) toast(done);
      setProblem("");
      return true;
    } catch (e) {
      setProblem(errorText(e));
      return false;
    } finally {
      setBusy(false);
    }
  };
  /** A number typed with a dot or a comma; null when it is not one. */
  const number = (text: string): number | null => {
    const n = Number(text.trim().replace(",", ".") || 0);
    return Number.isFinite(n) && n >= 0 ? n : null;
  };
  const saveTime = () => {
    const pr = number(price), hr = number(hours);
    if (pr === null || hr === null) {
      setProblem(`${pr === null ? "The price" : "The monthly limit"} is not a number. Type it like 0.44.`);
      return;
    }
    void act(() => processing.set({ price_per_hour: pr, month_hours: hr }), "Saved.");
  };

  if (!p) return problem ? <Banner tone="bad" title="Processing settings did not load">{problem}</Banner>
    : <p className="small muted">Loading…</p>;

  const check = p.worker.check;
  const used = p.usage.used_seconds;
  const limit = p.usage.limit_hours * 3600;
  const monthLine = `This month: ${fmtSpan(used)} of ${p.usage.limit_hours ? `${p.usage.limit_hours} h` : "0 h (off)"}` +
    (p.usage.cost !== null ? ` · ${fmtMoney(p.usage.cost)}` : "");
  const choose = (mode: ProcessingMode) => void act(() => processing.set({ mode }),
    mode === "full_cloud" ? "Make clips now runs on your worker." : mode === "hybrid"
      ? "Clips are made here; pictures and video on your cloud computer." : "Everything runs on this computer.");

  return (
    <div className="stack-4">
      {problem && <Banner tone="bad" title="That did not work">{problem}</Banner>}
      <section className="panel" aria-labelledby="pr-where">
        <h2 id="pr-where">Where Make clips runs</h2>
        <div className="mode-pick pr-modes" role="radiogroup" aria-label="Where Make clips runs">
          {p.modes.map((m) => (
            <label key={m.id} className={m.ready ? "" : "off"}>
              <input type="radio" name="processing-mode" checked={p.mode === m.id} disabled={busy || !m.ready}
                onChange={() => choose(m.id)} />
              <b>{m.name}{p.mode === m.id ? " (in use)" : ""}</b><span>{m.about}</span>
              {!m.ready && m.why && <span className="pr-why">{m.why}</span>}
            </label>
          ))}
        </div>
        <p className="small muted">Pictures and video for shorts are made on {p.pictures_on}.
          {p.mode === "full_cloud" && " Each new Make clips project uploads its video (or sends its link) to your worker" +
            " and brings the finished clips back here."}</p>
      </section>

      <section className="panel" aria-labelledby="pr-worker">
        <h2 id="pr-worker">Your ClipForge worker</h2>
        <p className="small muted">A worker is ClipForge on a computer you rent (a Linux server or a GPU machine you
          control), started with a key. It answers only your desktop, only with that key, and never posts anything.</p>
        <p className="small">{!p.worker.url ? <><Pill>Not set up</Pill> Add its address and key below.</>
          : !check ? <><Pill>Not checked yet</Pill> {p.worker.host}</>
          : check.ok ? <><Pill tone="good" icon="check">Connected</Pill> {p.worker.host}
            {check.version ? ` · ClipForge ${check.version}` : ""}
            {check.whisper?.model ? ` · transcription ${check.whisper.model} on ${check.whisper.device || "its CPU"}` : ""}
            {check.ai ? ` · AI: ${check.ai}` : ""}{check.busy ? " · busy with a job" : ""}</>
          : <><Pill tone="bad">Not answering</Pill> {check.why}</>}</p>
        <div className="row wrap pr-form">
          <label className="field grow"><span>Worker address</span><input value={url} spellCheck={false}
            autoComplete="off" placeholder="https://worker.example.com" onChange={(e) => setUrl(e.target.value)} /></label>
          <label className="field grow"><span>{p.worker.key_set ? "A new key (leave empty to keep it)" : "Worker key"}</span>
            <input type="password" value={key} autoComplete="off" onChange={(e) => setKey(e.target.value)} /></label>
          <button type="button" className="btn btn-small" disabled={busy || !url.trim()}
            onClick={() => void act(() => processing.worker(url.trim(), key.trim() || undefined))
              .then((ok) => { if (ok) setKey(""); })}>
            Save and check</button>
          {p.worker.url && <button type="button" className="btn btn-small btn-quiet" disabled={busy}
            onClick={() => void act(() => processing.get(true))}><Icon name="refresh" />Check again</button>}
          {p.worker.url && <button type="button" className="btn btn-small btn-quiet" disabled={busy}
            onClick={() => void act(() => processing.worker(""), "The worker is removed; Make clips runs here.")
              .then((ok) => { if (ok) setUrl(""); })}><Icon name="trash" />Remove worker</button>}
        </div>
        <p className="small muted">The key is kept locked on this computer and sent only to this address, over HTTPS.
          Changing the address forgets the key.</p>
        <Disclosure summary="How to start a worker">
          <ol className="small">
            <li>On the computer you rent: install Python 3.12 and FFmpeg, and copy ClipForge there.</li>
            <li>Make a key with <span className="mono">openssl rand -base64 32</span> and start ClipForge with it:
              {" "}<span className="mono">CLIPFOUNDRY_WORKER_KEY=… CLIPFOUNDRY_WORKERS=off python -m clipfoundry --host
              127.0.0.1</span>.</li>
            <li>Put HTTPS in front of it (Caddy does this in five lines), then paste its address and the key here.</li>
          </ol>
          <p className="small muted">Every step, with the Caddy setup and checks: deploy/WORKER.md in ClipForge&apos;s
            folder.</p>
        </Disclosure>
      </section>

      <section className="panel" aria-labelledby="pr-time">
        <h2 id="pr-time">Worker time</h2>
        <p className="small muted">Worker time is counted on the worker, from a job&apos;s start there to its end.
          ClipForge does not know what your provider charges: enter what an hour of your worker costs you and estimates
          show money too. Nothing is sent to the worker once this month&apos;s hours are used up.</p>
        <div className="row wrap pr-form">
          <label className="field"><span>Price of an hour ($)</span><input inputMode="decimal" value={price}
            placeholder="0.44" onChange={(e) => setPrice(e.target.value)} /></label>
          <label className="field"><span>Monthly limit (hours)</span><input inputMode="decimal" value={hours}
            onChange={(e) => setHours(e.target.value)} /></label>
          <button type="button" className="btn btn-small" disabled={busy} onClick={saveTime}>Save</button>
        </div>
        <div className="stack-2">
          <p className="small"><b>{monthLine}</b></p>
          <ProgressBar value={limit ? Math.min(1, used / limit) : 0} label={monthLine}
            tone={used < limit ? "good" : undefined} />
          <p className="small muted">The count starts again on {new Date(p.usage.resets_at * 1000)
            .toLocaleDateString([], { month: "long", day: "numeric" })}.</p>
        </div>
        {!!p.usage.runs.length && <Disclosure summary={`Recent worker jobs (${p.usage.runs.length})`}>
          <ul className="file-list small">{p.usage.runs.map((r) => (
            <li key={r.id}><span>{r.kind === "test" ? "Test job" : <a className="textlink" href={`#/project/${r.project_id}`}>
              Make clips</a>} · {new Date(r.started_at * 1000).toLocaleString([], { month: "short", day: "numeric",
              hour: "numeric", minute: "2-digit" })}</span>
              <span className="muted">{r.status} · {fmtSpan(r.seconds)}{r.cost !== null ? ` · ${fmtMoney(r.cost)}` : ""}
                {r.uploaded_bytes ? ` · ${fmtBytes(r.uploaded_bytes)} sent` : ""}</span></li>))}</ul>
        </Disclosure>}
      </section>

      <section className="panel" aria-labelledby="pr-test">
        <h2 id="pr-test">Test job</h2>
        <p className="small muted">A private test: ClipForge makes a one-minute video on this computer (nothing of
          yours), sends it to the worker as a Make clips job, brings the clip back, checks it plays and deletes it
          there. It counts as worker time.</p>
        <div className="row-actions">
          {testRunning
            ? <button type="button" className="btn btn-small" disabled={busy}
              onClick={() => void act(async () => { await processing.stopTest(); return processing.get(); })}>
              <Icon name="stop" />Stop the test</button>
            : <button type="button" className="btn btn-primary" disabled={busy || !p.worker.url}
              onClick={() => void act(async () => { await processing.test(); return processing.get(); })}>
              <Icon name="cloud" />Run a test job</button>}
        </div>
        {p.test && <TestResult t={p.test} running={testRunning} stages={p.stages} />}
      </section>

      <section className="panel" aria-labelledby="pr-here">
        <h2 id="pr-here">What stays on this computer</h2>
        <ul className="small">{p.unsupported.map((u) => <li key={u}>{u}</li>)}</ul>
      </section>
    </div>
  );
}

function TestResult({ t, running, stages }: { t: WorkerTest; running: boolean; stages: Processing["stages"] }) {
  if (running && t.job) return <div className="stack-2"><p className="small">{t.job.message || "Starting"}</p>
    <ProgressBar value={t.job.progress || 0} label={t.job.message || "Starting"} /></div>;
  const when = new Date((t.ended_at || t.started_at) * 1000).toLocaleString([], { month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit" });
  return (
    <div className="stack-2 pr-test">
      <p className="small">{t.ok ? <Pill tone="good" icon="check">The test worked</Pill>
        : t.status === "canceled" ? <Pill>Stopped</Pill> : <Pill tone="bad">The test failed</Pill>} {when} · {t.worker}</p>
      {!t.ok && t.problem && <p className="small">{t.problem}</p>}
      {!!t.ran && Object.keys(t.ran).length > 0 && <ul className="pr-stages" aria-label="Stages that ran on the worker">
        {stages.map((s) => <li key={s} className={t.ran?.[s] ? "on" : ""}>
          <Icon name={t.ran?.[s] ? "check" : "x"} className="sm" /><span>{STAGE_NAMES[s]}
            <span className="muted">{!t.ran?.[s] ? " · not run" : t.how?.[s]?.startsWith("import") ? " · given the words"
              : " · on the worker"}</span></span></li>)}
      </ul>}
      {t.note && <p className="small muted">{t.note}</p>}
      {t.ok && <p className="small">
        {t.upload_seconds !== undefined && <>Upload {fmtBytes(t.uploaded_bytes || 0)} in {fmtSpan(t.upload_seconds)}
          {t.upload_mbps ? ` (${t.upload_mbps} Mbit/s)` : ""} · </>}
        Worker time {fmtSpan(t.worker_seconds)}{t.cost !== undefined ? ` (${fmtMoney(t.cost)})` : ""} · start to finish
        {" "}{fmtSpan(t.round_trip_seconds)}
        {t.clip && <> · the clip: {t.clip.seconds} s, {t.clip.width}×{t.clip.height}, picture and sound play</>}</p>}
      {t.worker_info?.whisper?.model && <p className="small muted">Transcription on the worker: {t.worker_info.whisper.model}
        {" "}on {t.worker_info.whisper.device || "its CPU"}{t.worker_info.ai ? `; picking clips with ${t.worker_info.ai}` : ""}.</p>}
    </div>
  );
}
