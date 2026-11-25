/**
 * The project page's Full Cloud card (docs/clipforge/FULL_CLOUD.md): this project's clips are made on the owner's
 * worker. It says what was uploaded, the estimate and what it cost, the phase, which stages ran on the worker, the
 * log, and what stays on this computer. Stop is the page's own Cancel processing button.
 */
import { fmtBytes, fmtMoney, fmtSpan, ProjectCloud, STAGE_NAMES, WorkerStage } from "../processing";
import { Disclosure, Icon, Pill } from "./ui";

const PHASE: Record<ProjectCloud["phase"], string> = {
  waiting: "Waiting to start", upload: "Sending the video to your worker", running: "Making clips on your worker",
  fetching: "Bringing the clips back", done: "Made on your worker", failed: "Stopped with a problem",
  canceled: "Stopped", gone: "The worker no longer has this job",
};
const STAGES: WorkerStage[] = ["ingest", "transcribe", "analyze", "framing", "captions", "render"];

/** `status` is the project's own: a phase counts as working only while the project is queued or processing (a run
 * that failed before the worker had the job keeps its last phase). */
export function ProjectCloudCard({ c, status }: { c: ProjectCloud; status: string }) {
  const est = c.estimate;
  const active = status === "queued" || status === "processing";
  const phase: ProjectCloud["phase"] = active || !["waiting", "upload", "running", "fetching"].includes(c.phase)
    ? c.phase : status === "cancelled" ? "canceled" : "failed";
  const working = active && ["waiting", "upload", "running", "fetching"].includes(phase);
  const onWorker = active && (phase === "running" || phase === "fetching");  // the worker has the job: safe to close
  return (
    <section className="panel pc-cloud" aria-labelledby="pc-cloud-h">
      <div className="panel-head"><h2 id="pc-cloud-h">Full Cloud</h2>
        <Pill tone={phase === "done" ? "good" : phase === "failed" || phase === "gone" ? "bad" : "neutral"}
          icon={phase === "done" ? "check" : working ? "cloud" : undefined}>{PHASE[phase] || phase}</Pill></div>
      <p className="small">Worker: <b>{c.worker || "not started yet"}</b>
        {c.worker_info?.whisper?.model ? ` · transcription ${c.worker_info.whisper.model} on ${c.worker_info.whisper.device || "its CPU"}` : ""}
        {c.worker_info?.ai ? ` · clips picked with ${c.worker_info.ai}` : ""}</p>
      {!!c.uploaded.length && <p className="small">Sent to the worker: {c.uploaded.map((u, i) => (
        <span key={i}>{i ? ", " : ""}{u.link ? <>the link <span className="mono">{u.link}</span></>
          : u.what === "transcript" ? <>its transcript ({fmtBytes(u.bytes)})</> : <>{u.name} ({fmtBytes(u.bytes)})</>}
        </span>))}, with this
        computer&apos;s clip choices (length, count, captions, framing, sound) and this project&apos;s style choices.
        Nothing else.</p>}
      <p className="small">
        {est?.known ? <>Estimate: about {fmtSpan(est.seconds)} of worker time{est.cost !== null ? ` (${fmtMoney(est.cost)})` : ""}. </>
          : est ? "The estimate appears once the video's length is known. " : ""}
        {c.seconds ? <>Used: {fmtSpan(c.seconds)}{c.cost !== null && c.cost !== undefined ? ` (${fmtMoney(c.cost)})` : ""}.</> : ""}
      </p>
      {Object.keys(c.ran || {}).length > 0 && <ul className="pr-stages" aria-label="Stages that ran on the worker">
        {STAGES.map((s) => <li key={s} className={c.ran[s] ? "on" : ""}>
          <Icon name={c.ran[s] ? "check" : "dot"} className="sm" /><span>{STAGE_NAMES[s]}
            <span className="muted">{c.ran[s] ? (c.how?.[s]?.startsWith("import") ? " · from your transcript"
              : " · on the worker") : working ? " · not yet" : " · not run"}</span></span></li>)}
      </ul>}
      {onWorker && <p className="small muted">You can close ClipForge: the job carries on on your worker, and when
        ClipForge starts again it picks it up (without sending the video again) and brings the clips back.</p>}
      {!!c.log.length && <Disclosure summary={`What happened (${c.log.length})`} open={phase === "failed"}>
        <ol className="pc-log">{c.log.map((l, i) => <li key={i}><span className="muted">{new Date(l.at * 1000)
          .toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}</span> {l.text}</li>)}</ol>
      </Disclosure>}
      <Disclosure summary="What stays on this computer">
        <ul className="small">{c.unsupported.map((u) => <li key={u}>{u}</li>)}</ul>
      </Disclosure>
    </section>
  );
}
