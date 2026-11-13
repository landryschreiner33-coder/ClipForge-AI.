import { useEffect, useRef, useState } from "react";
import { api, errorText, SoundCheck } from "../api";
import { Icon, Segmented } from "./ui";

/** Before/after switch for "Clean up the sound": one player that swaps between the original and the cleaned sound
 * at the same moment, both at the same loudness, so the difference you hear is clarity and not volume. */
export function SoundCompare({ clipId, mode }: { clipId: string; mode: string }) {
  const level = mode === "off" ? "gentle" : mode;
  const [check, setCheck] = useState<SoundCheck | null>(null);
  const [which, setWhich] = useState<"before" | "after">("after");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const player = useRef<HTMLAudioElement>(null);
  const resume = useRef<{ at: number; playing: boolean } | null>(null);

  useEffect(() => { setCheck(null); setError(""); }, [clipId, level]);

  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const c = await api.soundCheck(clipId, level);
      setCheck(c);
      setWhich(c.after ? "after" : "before");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const swap = (next: "before" | "after") => {
    const a = player.current;
    if (a) resume.current = { at: a.currentTime, playing: !a.paused };
    setWhich(next);
  };

  const src = check ? (which === "after" && check.after ? check.after : check.before) : "";
  return (
    <div className="field">
      <span className="label">Hear the difference</span>
      {!check && (
        <div className="row wrap">
          <button type="button" className="btn btn-small" disabled={busy} onClick={run}>
            <Icon name={busy ? "refresh" : "play"} />
            {busy ? "Cleaning up the sound…" : `Compare before and after (${level === "auto" ? "Auto" : level === "strong" ? "Strong" : "Gentle"})`}
          </button>
        </div>
      )}
      {check && (
        <>
          {check.after ? (
            <Segmented label="Which sound to play" value={which} onChange={swap}
              options={[{ value: "before", label: "Before" }, { value: "after", label: "After" }]} />
          ) : null}
          <audio ref={player} controls preload="auto" src={src} style={{ width: "100%" }}
            onLoadedMetadata={(e) => {
              const r = resume.current;
              resume.current = null;
              if (!r) return;
              e.currentTarget.currentTime = Math.min(r.at, e.currentTarget.duration || r.at);
              if (r.playing) void e.currentTarget.play().catch(() => undefined);
            }} />
          <p className="hint">{check.summary} Both are played at the same loudness; this uses the clip's saved trim.</p>
        </>
      )}
      {error && <p className="hint" role="alert">{error}</p>}
    </div>
  );
}
