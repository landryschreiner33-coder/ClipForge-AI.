import { useCallback, useEffect, useId, useRef, useState } from "react";
import { api, Clip, ClipVersion, errorText, fmtTime, versionVideoUrl } from "../api";
import { ConfirmDialog, Icon, Modal, Pill, Segmented, toast } from "./ui";

const BUSY = ["queued", "rendering"];

/**
 * Versions of a clip: create them, watch them render, compare, and choose the one used for export and posts.
 * `onPlay`/`playing` (optional) let a page show a version in its own player.
 */
export function VersionsCard({ clip, onChange, onPlay, playing }: {
  clip: Clip;
  onChange: (active: ClipVersion | undefined, all: ClipVersion[]) => void;
  onPlay?: (v: ClipVersion) => void;
  playing?: string;
}) {
  const [list, setList] = useState<ClipVersion[]>([]);
  const [active, setActive] = useState(clip.active_version || "");
  const [comparing, setComparing] = useState(false);
  const [asking, setAsking] = useState(false);
  const [deleting, setDeleting] = useState<ClipVersion | null>(null);
  const [busy, setBusy] = useState(false);
  const hid = useId();
  const name = useId();

  // The latest callback, so a page that passes a new function on every render doesn't reload the list each time.
  const changed = useRef(onChange);
  changed.current = onChange;
  const apply = useCallback((r: { active: string; versions: ClipVersion[] }) => {
    // A chosen version that no longer exists means the original is used (as the backend does).
    const act = r.versions.some((v) => v.id === r.active) ? r.active : "";
    setList(r.versions);
    setActive(act);
    changed.current(r.versions.find((v) => v.id === act), r.versions);
  }, []);

  const load = useCallback(() => api.versions(clip.id).then(apply).catch(() => undefined), [clip.id, apply]);
  useEffect(() => {
    load();
  }, [load, clip.version, clip.status]);
  const rendering = list.some((v) => BUSY.includes(v.status));
  useEffect(() => {
    if (!rendering) return;
    const t = setTimeout(load, 1500);
    return () => clearTimeout(t);
  }, [rendering, list, load]);

  const run = async (fn: () => Promise<{ active: string; versions: ClipVersion[] }>) => {
    setBusy(true);
    try {
      apply(await fn());
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setBusy(false);
    }
  };
  const missing = list.length <= 1;
  const ready = list.filter((v) => v.status === "ready" && v.has_video);
  const canCreate = clip.status === "ready" && !rendering;

  return (
    <section className="timeline" aria-labelledby={hid}>
      <div className="panel-head">
        <div className="section-title">
          <h2 id={hid} style={{ fontSize: "var(--fs-h3)" }}>Versions</h2>
          <span className="tiny faint">Compare, then choose the one used for export and posts.</span>
        </div>
        <div className="row wrap">
          <button type="button" className="btn btn-small" disabled={busy || !canCreate} onClick={() => setAsking(true)}>
            <Icon name="spark" />{missing ? "Create versions…" : "Make versions again…"}
          </button>
          <button type="button" className="btn btn-small" disabled={ready.length < 2}
            onClick={() => setComparing(true)}>
            <Icon name="play" />Compare
          </button>
        </div>
      </div>
      {clip.status !== "ready" && (
        <p className="tiny faint">
          Versions are made from the rendered clip, so they can be created once it is rendered.
        </p>
      )}
      {list.length > 0 && (
        <div className="versions" role="radiogroup" aria-label="Version used for export and posts">
          {list.map((v) => {
            const on = active === v.id;
            const isBusy = BUSY.includes(v.status);
            return (
              <div key={v.id || "original"} className={`version ${on ? "on" : ""}`}>
                <label className="choice" style={{ padding: 0 }}>
                  <input type="radio" name={name} checked={on} disabled={v.status !== "ready" || busy}
                    onChange={() => run(() => api.setActiveVersion(clip.id, v.id))} />
                  <span className="stack" style={{ gap: 0 }}>
                    <b className="small">{v.label}</b>
                    {v.has_video && v.status === "ready" && (
                      <span className="tiny faint tnum">{fmtTime(v.duration)}</span>
                    )}
                  </span>
                </label>
                <span className="tiny faint">{v.description}</span>
                {v.status === "queued" && <Pill tone="neutral" icon="clock">Waiting to render</Pill>}
                {v.status === "rendering" && (
                  <Pill tone="info" icon="refresh">Rendering {Math.round(v.progress * 100)}%</Pill>
                )}
                {v.status === "error" && (
                  <>
                    <Pill tone="bad" icon="alert">Render failed</Pill>
                    {v.error && <span className="tiny muted break">{v.error}</span>}
                  </>
                )}
                {v.stale && (
                  <span className="tiny warn-text">
                    Made from an older edit of the clip. Make the versions again to update it.
                  </span>
                )}
                {on && <span className="tiny"><Icon name="check" className="xs" /> Used for export and posts</span>}
                {(onPlay || v.id) && (
                  <div className="row wrap" style={{ gap: 4 }}>
                    {onPlay && v.status === "ready" && v.has_video && (
                      <button type="button" className="btn btn-small btn-quiet" aria-pressed={playing === v.id}
                        aria-label={`Show “${v.label}” in the preview`} onClick={() => onPlay(v)}>
                        <Icon name={playing === v.id ? "check" : "play"} />{playing === v.id ? "Showing" : "Preview"}
                      </button>
                    )}
                    {v.id && (
                      <button type="button" className="btn btn-small btn-quiet" disabled={busy || isBusy}
                        aria-label={`Delete the “${v.label}” version`} onClick={() => setDeleting(v)}>
                        <Icon name="trash" />Delete…
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {asking && (
        <ConfirmDialog title={missing ? "Create versions?" : "Make the versions again?"}
          confirmLabel={missing ? "Create versions" : "Make versions again"} onClose={() => setAsking(false)}
          onConfirm={async () => {
            apply(await api.createVersions(clip.id));
            toast("Rendering the versions");
          }}>
          <p className="muted small">ClipFoundry renders three alternatives next to the original:</p>
          <ul className="steps-list">
            <li><b>Faster pacing:</b> tighter pauses, no filler words, 8% faster.</li>
            <li><b>Alternative hook:</b> another hook line, and a stronger first line if the clip has one.</li>
            <li><b>Alternative caption style:</b> contrasting captions with key words emphasized.</li>
          </ul>
          <p className="small">
            {missing ? "The original stays as it is."
              : "Versions already made are replaced with new renders of the clip as it is now."}
            {" "}You then choose which one is used for export and posts. A version used by a post gets its own final
            check.
          </p>
        </ConfirmDialog>
      )}
      {deleting && (
        <ConfirmDialog title={`Delete the “${deleting.label}” version?`} confirmLabel="Delete version" danger
          onClose={() => setDeleting(null)}
          onConfirm={async () => {
            apply(await api.deleteVersion(deleting.id));
            toast(`Deleted the “${deleting.label}” version`);
          }}>
          <p className="muted">
            Its video file is deleted from this computer. The original clip and the other versions stay.
          </p>
          {active === deleting.id && (
            <p className="small">It is used for export and posts now; after this, the original is used.</p>
          )}
        </ConfirmDialog>
      )}
      {comparing && (
        <CompareModal clip={clip} versions={ready} active={active}
          onPick={(id) => run(() => api.setActiveVersion(clip.id, id))} onClose={() => setComparing(false)} />
      )}
    </section>
  );
}

/** Side by side (played together, sound from one) or one after another in a single player. */
function CompareModal({ clip, versions, active, onPick, onClose }: {
  clip: Clip; versions: ClipVersion[]; active: string; onPick: (id: string) => void; onClose: () => void;
}) {
  const [mode, setMode] = useState<"side" | "sequence">("side");
  const [soundFrom, setSoundFrom] = useState(0);
  const [seqIndex, setSeqIndex] = useState(0);
  const refs = useRef<(HTMLVideoElement | null)[]>([]);
  const seqRef = useRef<HTMLVideoElement | null>(null);
  const hid = useId();
  const sound = useId();

  const playAll = () => {
    refs.current.forEach((v, i) => {
      if (!v) return;
      v.currentTime = 0;
      v.muted = i !== soundFrom;
      v.play().catch(() => undefined);
    });
  };
  const pauseAll = () => refs.current.forEach((v) => v?.pause());
  useEffect(() => {
    refs.current.forEach((v, i) => v && (v.muted = i !== soundFrom));
  }, [soundFrom]);
  useEffect(() => {
    if (mode === "sequence" && seqRef.current) {
      seqRef.current.load();
      seqRef.current.play().catch(() => undefined);
    }
  }, [mode, seqIndex]);
  const switchMode = (m: "side" | "sequence") => {
    pauseAll();
    setSeqIndex(0);
    setMode(m);
  };

  const current = versions[seqIndex];
  return (
    <Modal onClose={onClose} labelledBy={hid} className="compare">
      <div className="panel-head">
        <h2 id={hid}>Compare versions</h2>
        <button type="button" className="btn btn-small btn-icon" aria-label="Close" onClick={onClose}>
          <Icon name="x" />
        </button>
      </div>
      <div className="row wrap">
        <Segmented label="How to compare" value={mode} onChange={switchMode}
          options={[{ value: "side", label: "Side by side" }, { value: "sequence", label: "One after another" }]} />
        {mode === "side" && (
          <>
            <button type="button" className="btn btn-small" onClick={playAll}>
              <Icon name="play" />Play all from the start
            </button>
            <button type="button" className="btn btn-small" onClick={pauseAll}><Icon name="pause" />Pause</button>
          </>
        )}
      </div>
      {mode === "side" ? (
        <div className="compare-grid" style={{ gridTemplateColumns: `repeat(${versions.length}, minmax(0, 1fr))` }}>
          {versions.map((v, i) => (
            <div key={v.id || "o"} className={`compare-cell ${active === v.id ? "on" : ""}`}>
              <video ref={(el) => (refs.current[i] = el)} src={versionVideoUrl(clip, v)} playsInline controls
                muted={i !== soundFrom} aria-label={v.label} />
              <b className="small">{v.label}</b>
              <span className="tiny faint tnum">{fmtTime(v.duration)}</span>
              <label className="choice" style={{ minHeight: 0 }}>
                <input type="radio" name={sound} checked={soundFrom === i} onChange={() => setSoundFrom(i)} />
                <span className="small">Sound from this one</span>
              </label>
              {active === v.id ? (
                <span className="small"><Icon name="check" className="xs" /> Used for export and posts</span>
              ) : (
                <button type="button" className="btn btn-small" onClick={() => onPick(v.id)}>Use this version</button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="sequence">
          <video ref={seqRef} src={current ? versionVideoUrl(clip, current) : undefined} playsInline controls
            aria-label={current?.label} onEnded={() => setSeqIndex((i) => (i + 1 < versions.length ? i + 1 : i))} />
          <div className="seq-side">
            {versions.map((v, i) => (
              <button key={v.id || "o"} type="button" className={`opt ${i === seqIndex ? "on" : ""}`}
                aria-pressed={i === seqIndex}
                onClick={() => setSeqIndex(i)}>
                {i + 1}. {v.label} · {fmtTime(v.duration)}
              </button>
            ))}
            <p className="small muted">Plays each version in turn. Now playing: <b>{current?.label}</b></p>
            {current && (active === current.id ? (
              <span className="small"><Icon name="check" className="xs" /> Used for export and posts</span>
            ) : (
              <button type="button" className="btn" onClick={() => onPick(current.id)}>Use “{current.label}”</button>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
}
