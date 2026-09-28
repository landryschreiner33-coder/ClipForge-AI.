import { useCallback, useEffect, useRef, useState } from "react";
import { api, Clip, ClipVersion, errorText, fmtTime, versionThumbUrl, versionVideoUrl } from "../api";
import { Icon, Modal, toast } from "./ui";

const BUSY = ["queued", "rendering"];

/** Versions of a clip: create them, watch them render, compare, and choose the one to publish and export. */
export function VersionsCard({ clip, onChange }: { clip: Clip; onChange: (active: ClipVersion | undefined, all: ClipVersion[]) => void }) {
  const [list, setList] = useState<ClipVersion[]>([]);
  const [active, setActive] = useState(clip.active_version || "");
  const [comparing, setComparing] = useState(false);
  const [busy, setBusy] = useState(false);

  const apply = useCallback((r: { active: string; versions: ClipVersion[] }) => {
    setList(r.versions);
    setActive(r.active);
    onChange(r.versions.find((v) => v.id === r.active), r.versions);
  }, [onChange]);

  const load = useCallback(() => api.versions(clip.id).then(apply).catch(() => undefined), [clip.id, apply]);
  useEffect(() => {
    load();
  }, [load]);
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

  return (
    <div className="card">
      <div className="row between wrap" style={{ marginBottom: 10 }}>
        <h3 style={{ margin: 0 }}>Versions <span className="muted small" style={{ fontWeight: 400 }}>compare, then choose which one to publish</span></h3>
        <div className="row">
          <button className="btn sm" disabled={busy || rendering || clip.status !== "ready"} onClick={() => run(() => api.createVersions(clip.id))}>
            <Icon name="spark" size={14} /> {missing ? "Create versions" : "Re-render versions"}
          </button>
          <button className="btn sm" disabled={ready.length < 2} onClick={() => setComparing(true)}><Icon name="play" size={13} /> Compare</button>
        </div>
      </div>
      {missing && (
        <p className="small muted" style={{ marginTop: 0 }}>
          Render three alternatives next to the original: <b>Faster pacing</b> (tighter pauses, no filler words, 8% faster),
          <b> Alternative hook</b> (another hook line, and a stronger first line if the clip has one) and
          <b> Alternative caption style</b> (contrasting captions with key words emphasized).
        </p>
      )}
      <div className="versions">
        {list.map((v) => (
          <div key={v.id || "original"} className={`ver ${active === v.id ? "on" : ""}`}>
            <div className="ver-thumb" style={v.has_thumbnail ? { backgroundImage: `url(${versionThumbUrl(clip, v)})` } : undefined}>
              {BUSY.includes(v.status) && (
                <div className="overlay"><div className="spinner" /><div className="small">{v.status === "queued" ? "Queued" : `Rendering ${Math.round(v.progress * 100)}%`}</div></div>
              )}
              {v.status === "error" && <div className="overlay"><span className="badge bad">Failed</span><div className="small">{v.error}</div></div>}
              {v.has_video && v.status === "ready" && <span className="dur">{fmtTime(v.duration)}</span>}
            </div>
            <div className="ver-body">
              <b>{v.label}</b>
              <div className="small muted">{v.description}</div>
              {v.stale && <div className="small warn-text">Made from an older edit of the clip: re-render to update.</div>}
              <label className="row small mt-s">
                <input type="radio" checked={active === v.id} disabled={v.status !== "ready"}
                  onChange={() => run(() => api.setActiveVersion(clip.id, v.id))} />
                {active === v.id ? "Publishing this version" : "Use this version"}
              </label>
              {v.id && (
                <button className="btn ghost sm" disabled={busy || BUSY.includes(v.status)}
                  onClick={() => window.confirm(`Delete the “${v.label}” version?`) && run(() => api.deleteVersion(v.id))}>
                  <Icon name="trash" size={12} /> Delete
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
      {comparing && <CompareModal clip={clip} versions={ready} active={active} onPick={(id) => run(() => api.setActiveVersion(clip.id, id))} onClose={() => setComparing(false)} />}
    </div>
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

  const current = versions[seqIndex];
  return (
    <Modal onClose={onClose}>
      <div className="compare">
        <div className="row between wrap" style={{ marginBottom: 12 }}>
          <div className="segmented">
            <button className={mode === "side" ? "on" : ""} onClick={() => { setMode("side"); }}>Side by side</button>
            <button className={mode === "sequence" ? "on" : ""} onClick={() => { pauseAll(); setSeqIndex(0); setMode("sequence"); }}>One after another</button>
          </div>
          {mode === "side" && (
            <div className="row">
              <button className="btn sm primary" onClick={playAll}><Icon name="play" size={12} /> Play all from the start</button>
              <button className="btn sm" onClick={pauseAll}>Pause</button>
            </div>
          )}
          <button className="btn ghost icon-btn" onClick={onClose}><Icon name="x" /></button>
        </div>
        {mode === "side" ? (
          <div className="compare-grid" style={{ gridTemplateColumns: `repeat(${versions.length}, minmax(0, 1fr))` }}>
            {versions.map((v, i) => (
              <div key={v.id || "o"} className={`compare-cell ${active === v.id ? "on" : ""}`}>
                <video ref={(el) => (refs.current[i] = el)} src={versionVideoUrl(clip, v)} playsInline controls muted={i !== soundFrom} />
                <b>{v.label}</b>
                <span className="small muted">{fmtTime(v.duration)}</span>
                <label className="row small"><input type="radio" checked={soundFrom === i} onChange={() => setSoundFrom(i)} /> Sound</label>
                <button className={`btn sm ${active === v.id ? "primary" : ""}`} onClick={() => onPick(v.id)}>
                  {active === v.id ? "✓ Publishing this" : "Use this version"}
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="sequence">
            <video ref={seqRef} src={current ? versionVideoUrl(clip, current) : undefined} playsInline controls
              onEnded={() => setSeqIndex((i) => (i + 1 < versions.length ? i + 1 : i))} />
            <div className="seq-side">
              {versions.map((v, i) => (
                <button key={v.id || "o"} className={`opt ${i === seqIndex ? "on" : ""}`} onClick={() => setSeqIndex(i)}>
                  {i + 1}. {v.label} · {fmtTime(v.duration)}
                </button>
              ))}
              <div className="small muted">Plays each version in turn. Now playing: <b>{current?.label}</b></div>
              {current && (
                <button className={`btn ${active === current.id ? "primary" : ""}`} onClick={() => onPick(current.id)}>
                  {active === current.id ? "✓ Publishing this version" : `Use “${current.label}”`}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
