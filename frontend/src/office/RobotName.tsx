import { useState } from "react";
import { errorText } from "../api";
import { toast } from "../components/ui";
import { useAppearance } from "../prefs";
import { studio } from "../studio";
import { BY_ID, CORE } from "./cast";

const NAME_MAX = 32;  // the server's limit (studio/prefs.py NAME_MAX), counted in characters, so ✨ or é count once

/** Rename one robot (or the Brain Core) in place: Save, Reset name, Cancel. A name is display text only; the robot's
 * id, role, routing and permissions never change. The server cleans and checks the name, so its message is shown. */
export function RobotNameEditor({ id }: { id: string }) {
  const c = id === CORE.id ? CORE : BY_ID[id];
  const { refreshNames } = useAppearance();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(c?.name || "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (!c) return null;
  const save = async (reset = false) => {
    setError("");
    const text = draft.trim();
    if (!reset && !text) {
      setError("Type a name, or use Reset name.");
      return;
    }
    if (!reset && [...text].length > NAME_MAX) {
      setError(`Use at most ${NAME_MAX} characters (${[...text].length} now).`);
      return;
    }
    setBusy(true);
    try {
      if (reset) await studio.resetRobot(id);
      else await studio.renameRobot(id, text);
      await refreshNames();
      setEditing(false);
      toast(reset ? `Name reset for ${c.title}` : `${c.title} is now called ${text}`);
    } catch (e) {
      setError(errorText(e));
    }
    setBusy(false);
  };
  if (!editing) {
    return <button type="button" className="link-btn small" onClick={() => { setDraft(c.name); setEditing(true); }}
      aria-label={`Rename ${c.name}, ${c.title}`}>Rename</button>;
  }
  return (
    <form className="robot-name-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
      <label className="sr-only" htmlFor={`name-${id}`}>New name for {c.title}</label>
      <input id={`name-${id}`} value={draft} maxLength={64} onChange={(e) => setDraft(e.target.value)} autoFocus
        aria-invalid={!!error} aria-describedby={error ? `err-${id}` : undefined}
        onKeyDown={(e) => e.key === "Escape" && (e.stopPropagation(), setEditing(false))} />
      <button type="submit" className="btn btn-small btn-primary" disabled={busy}>Save</button>
      <button type="button" className="btn btn-small" disabled={busy} onClick={() => void save(true)}>Reset name</button>
      <button type="button" className="btn btn-small btn-quiet" onClick={() => setEditing(false)}>Cancel</button>
      {error && <span id={`err-${id}`} className="error-text small block" role="alert">{error}</span>}
    </form>
  );
}
