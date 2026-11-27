import { useEffect, useState } from "react";
import { api, TrimSuggestion, TrimSuggestions } from "../api";
import { Icon } from "./ui";

/** The clip's suggested trims, each with its reason. Use puts the change into the editor's unsaved edit, so it can
 * be checked on the timeline before saving (and undone like any other change). Read for the clip as saved. */
export function SuggestedTrims({ clipId, version, onUse }: {
  clipId: string; version: number | string; onUse: (s: TrimSuggestion) => void;
}) {
  const [data, setData] = useState<TrimSuggestions | null>(null);
  const [failed, setFailed] = useState(false);
  const [used, setUsed] = useState<string[]>([]);
  useEffect(() => {
    let alive = true;
    setFailed(false);
    setUsed([]);
    api.clipTrims(clipId).then((d) => alive && setData(d)).catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [clipId, version]);
  if (failed) return <p className="hint">Suggested trims could not be read for this clip.</p>;
  if (!data) return null;
  const shown = data.suggestions;
  return (
    <section className="trim-suggestions" aria-label="Suggested trims">
      <h4 className="small">Suggested trims</h4>
      {shown.length === 0 && (
        <p className="small muted">None: the clip starts and ends on whole sentences with no warm-up or outro to cut.</p>
      )}
      <ul className="plain stack">
        {shown.map((s) => (
          <li key={s.id} className="row wrap top">
            <div className="stack grow">
              <b className="small">{s.label}{" "}
                <span className="faint tnum">
                  ({s.seconds >= 0 ? `${s.seconds.toFixed(1)} s shorter` : `${(-s.seconds).toFixed(1)} s longer`})
                </span>
              </b>
              <span className="small muted">{s.why}</span>
            </div>
            <button type="button" className="btn btn-small" disabled={used.includes(s.id)}
              onClick={() => { onUse(s); setUsed((u) => [...u, s.id]); }}>
              <Icon name="check" />{used.includes(s.id) ? "Used" : "Use"}
            </button>
          </li>
        ))}
      </ul>
      {data.kept_pauses.length > 0 && (
        <p className="tiny faint">
          Kept on purpose: {data.kept_pauses.map((k) => `${k.why.replace("Builds tension: ", "")} (${k.seconds.toFixed(1)} s)`)
            .join(" · ")}. Remove pauses shortens these but never takes them out.
        </p>
      )}
    </section>
  );
}
