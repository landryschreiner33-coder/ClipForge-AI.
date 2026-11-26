/** Make → Check a video: the viral predictor on any short video (a draft, an edit from another app, a video to learn
 * from). It is transcribed and measured on this computer; the video is never sent anywhere. */
import { useEffect, useRef, useState } from "react";
import { at } from "../format";
import { errorText } from "../api";
import { PredictorBadge, PredictorPanel } from "../components/predictor";
import { FileDrop, Picked, UploadRow, useUploadsByFile } from "../components/studioParts";
import { Banner, ConfirmDialog, Icon, PageHead, toast } from "../components/ui";
import { predictor, PREDICTOR_NOTE, ViralCheck } from "../predictor";
import "../components/predictor.css";

const busyCheck = (c: ViralCheck) => c.status === "queued" || c.status === "checking";

export default function CheckVideo({ id }: { id: string }) {
  const [list, setList] = useState<ViralCheck[] | null>(null);
  const [open, setOpen] = useState<ViralCheck | null>(null);
  const [problem, setProblem] = useState("");
  const [picked, setPicked] = useState<Picked | null>(null);
  const [dropKey, setDropKey] = useState(0);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const sent = useRef(new Set<string>());
  const uploaded = useUploadsByFile();
  const video = useRef<HTMLVideoElement>(null);
  const [tick, setTick] = useState(0);

  const load = () => predictor.checks().then(setList).catch((e) => setProblem(errorText(e)));
  useEffect(() => {
    void load();
  }, []);
  const chosen = id || list?.[0]?.id || "";
  useEffect(() => {
    if (!chosen) {
      setOpen(null);
      return;
    }
    let alive = true;
    predictor.check(chosen).then((c) => alive && setOpen(c)).catch(() => alive && setOpen(null));
    return () => {
      alive = false;
    };
  }, [chosen, tick]);
  // While a check runs, follow it.
  const running = (list || []).some(busyCheck) || (open ? busyCheck(open) : false);
  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(() => {
      void load();
      setTick((n) => n + 1);
    }, 1500);
    return () => clearTimeout(timer);
  }, [running, list, open]);

  // A dropped video is checked as soon as its upload finishes.
  useEffect(() => {
    const asset = picked?.asset;
    if (!asset || sent.current.has(asset.id)) return;
    sent.current.add(asset.id);
    predictor.addCheck({ asset_id: asset.id, upload_ids: uploaded.of([asset.id]) }).then((c) => {
      toast(`Checking “${c.title}”. It shows here when it is ready.`);
      setPicked(null);
      setDropKey((n) => n + 1);
      window.location.hash = `#/create/check/${c.id}`;
      void load();
    }).catch((e) => {
      sent.current.delete(asset.id);
      setProblem(errorText(e));
    });
  }, [picked?.asset]); // eslint-disable-line react-hooks/exhaustive-deps

  const seek = (t: number) => {
    const v = video.current;
    if (!v) return;
    v.currentTime = t;
    void v.play().catch(() => undefined);
  };
  const act = async (fn: () => Promise<unknown>) => {
    setProblem("");
    try {
      await fn();
      await load();
      setTick((n) => n + 1);
    } catch (e) {
      setProblem(errorText(e));
    }
  };
  const r = open?.result;

  return (
    <div className="page">
      <PageHead kind="Make" title="Check a video"
        sub={<span className="small muted">
          Drop in a short video (up to 10 minutes). ClipForge watches it on this computer and predicts how it will do: a
          viral score, the hook, how long people stay, the strongest moment, and what to fix. The video is never sent
          anywhere.
        </span>} />
      {problem && <Banner tone="bad" title="That didn't work">{problem}</Banner>}
      <div className="vp-check-layout">
        <div className="stack-3">
          {picked && !picked.asset ? <UploadRow row={picked} />
            : <FileDrop key={dropKey} accept="video/*,.mkv,.m4v,.mov" label="Drop a video to check" button="Choose a video"
              onAssets={(rows) => setPicked(rows[0] || null)} onUploaded={uploaded.add} />}
          <h2 className="small">Checked videos</h2>
          {list === null ? <p className="small muted">Loading…</p> : list.length === 0 ? (
            <p className="small muted">Nothing checked yet. Clips you make are predicted on their own: see each clip's editor.</p>
          ) : (
            <ul className="vp-check-list">
              {list.map((c) => (
                <li key={c.id}>
                  <button type="button" aria-current={c.id === chosen} onClick={() => { window.location.hash = `#/create/check/${c.id}`; }}>
                    <Icon name="video" />
                    <span className="grow stack-1">
                      <b className="clamp-1">{c.title}</b>
                      {c.summary ? <PredictorBadge p={c.summary} />
                        : <span className="tiny faint">{c.status === "failed" ? "Couldn't be checked" : c.message}</span>}
                      <span className="tiny faint">{at(c.updated_at)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="stack-3">
          {!open ? <p className="muted">Choose a video to see its prediction.</p> : (
            <>
              <div className="row top wrap">
                <h2 className="grow break">{open.title}</h2>
                {busyCheck(open) ? (
                  <button type="button" className="btn btn-small" onClick={() => act(() => predictor.cancelCheck(open.id))}>
                    <Icon name="stop" />Stop
                  </button>
                ) : (
                  <button type="button" className="btn btn-small" onClick={() => act(() => predictor.checkAgain(open.id))}>
                    <Icon name="refresh" />Check again
                  </button>
                )}
                <button type="button" className="btn btn-small btn-quiet" onClick={() => setConfirmDelete(true)}>
                  <Icon name="trash" />Delete
                </button>
              </div>
              <video ref={video} src={open.media_url} controls playsInline preload="metadata" className="vp-check-video"
                aria-label={`Video: ${open.title}`} />
              {busyCheck(open) && (
                <p className="small row" role="status" style={{ gap: 8 }}>
                  <span className="inline-spinner" aria-hidden="true" /><b>{open.message || "Checking"}</b>
                </p>
              )}
              {open.status === "failed" && <Banner tone="bad" title="It couldn't be checked">{open.error}</Banner>}
              {open.status === "canceled" && <p className="small muted">Stopped. Press Check again to check it.</p>}
              {r && <PredictorPanel p={r} onSeek={seek} headingLevel={2} />}
              {r && <p className="tiny faint">{PREDICTOR_NOTE} To change a video ClipForge did not make, use the advice
                above in your editor, or make clips from it: clips ClipForge makes get fixes you can add with one press.</p>}
            </>
          )}
        </div>
      </div>
      {confirmDelete && open && (
        <ConfirmDialog title="Delete this check?" confirmLabel="Delete check" danger onClose={() => setConfirmDelete(false)}
          onConfirm={() => act(async () => {
            const done = await predictor.deleteCheck(open.id);
            toast(done.notes.join(" "));
            window.location.hash = "#/create/check";
          })}>
          <p className="muted">The prediction is deleted. The video file stays in your media.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
