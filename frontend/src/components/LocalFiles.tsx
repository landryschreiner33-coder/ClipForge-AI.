import { useEffect, useState } from "react";
import { errorText } from "../api";
import { Asset, fmtBytes, LocalListing, studio } from "../studio";
import { Icon, toast } from "./ui";
import "./longVideo.css";

/** Add from this computer (desktop only): browse your own folders and external drives and use files where they
 * are. Nothing is copied or uploaded, so a 17 GB recording is added in a moment; ClipForge keeps what it makes
 * for the file (sound, transcript, preview copy) in its own data folder and never changes the file. */
export function LocalFiles({ onLinked, onClose }: { onLinked: (assets: Asset[]) => void; onClose: () => void }) {
  const [listing, setListing] = useState<LocalListing | null>(null);
  const [problem, setProblem] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const open = (path: string) => {
    setProblem("");
    studio.localBrowse(path).then(setListing).catch((e) => setProblem(errorText(e)));
  };
  useEffect(() => open(""), []);
  const add = async () => {
    setBusy(true);
    try {
      const r = await studio.linkLocal(picked);
      if (r.assets.length) {
        onLinked(r.assets);
        r.assets.forEach((a) => { if (a.kind === "video") studio.prepareAsset(a.id).catch(() => undefined); });
      }
      if (r.problems.length) toast(r.problems.map((p) => `${p.path.split(/[\\/]/).pop()}: ${p.detail}`).join(" "), true);
      else toast(`Added ${r.assets.length} file${r.assets.length === 1 ? "" : "s"}, used where ${r.assets.length === 1 ? "it is" : "they are"}.`);
      setPicked([]);
      if (!r.problems.length) onClose();
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
  };
  const crumbs = listing?.path ? listing.path.split(/[\\/]/).filter(Boolean) : [];
  return (
    <div className="local-browser" role="group" aria-label="Add from this computer">
      <p className="small muted">Files are used where they are: nothing is copied or uploaded, and the files are never changed. Keep them where they are while this project exists (moving a file within these folders is found again).</p>
      <div className="local-crumbs">
        <button type="button" className="btn btn-small" disabled={!listing || !listing.path} onClick={() => open("")}><Icon name="home" />Places</button>
        {listing?.parent !== undefined && listing.path && <button type="button" className="btn btn-small" onClick={() => open(listing.parent)}><Icon name="back" />Up</button>}
        {listing?.path && <span className="small muted clamp-1" title={listing.path}>{crumbs.join(" › ")}</span>}
      </div>
      {problem && <p className="error-text small">{problem}</p>}
      {listing && (
        <ul className="local-list">
          {listing.folders.map((f) => (
            <li key={f.path}><button type="button" className="link-btn name" onClick={() => open(f.path)}><Icon name="folder" /> {f.name}</button></li>
          ))}
          {listing.files.map((f) => (
            <li key={f.path}>
              <label><input type="checkbox" checked={picked.includes(f.path)} onChange={(e) => setPicked((p) => e.target.checked ? [...p, f.path] : p.filter((x) => x !== f.path))} />
                <span className="name">{f.name}</span><span className="small muted">{fmtBytes(f.size)} · {f.kind}</span></label>
            </li>
          ))}
          {!listing.folders.length && !listing.files.length && <li className="muted small">No folders or media files here.</li>}
          {listing.truncated && <li className="muted small">Only the first 500 entries are shown; open a folder with fewer files.</li>}
        </ul>
      )}
      <div className="row-actions">
        <button type="button" className="btn btn-primary" disabled={!picked.length || busy} onClick={add}><Icon name="plus" />{busy ? "Adding…" : `Use ${picked.length || ""} file${picked.length === 1 ? "" : "s"} where ${picked.length === 1 ? "it is" : "they are"}`}</button>
        <button type="button" className="btn" disabled={busy} onClick={onClose}>Close</button>
      </div>
    </div>
  );
}
