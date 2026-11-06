import { useEffect, useState } from "react";
import { errorText } from "../api";
import { FilmCraftOpen, FilmCraftStatus, studio, Video } from "../studio";
import { Disclosure, Icon, toast } from "./ui";

/** Finish a version by hand in FilmCraft, the free open-source editor from the ArtCraft team (colour, keyframes,
 * titles, mixing). ClipForge writes the cut as an OpenTimelineIO timeline with SRT captions next to the video and
 * FilmCraft opens it; the files stay where they are. The online studio offers the timeline as a download only. */
export function FinishInFilmCraft({ v }: { v: Video }) {
  const [st, setSt] = useState<FilmCraftStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<FilmCraftOpen | null>(null);
  const rev = v.plan_revision;

  useEffect(() => { studio.filmcraft().then(setSt).catch(() => setSt(null)); }, []);

  const open = async (reveal: boolean) => {
    setBusy(true);
    try {
      const r = await studio.openInFilmCraft(v.id, rev, reveal);
      setLast(r);
      if (reveal) toast(r.revealed ? "Showing the timeline files." : `The timeline files are in ${r.folder}`);
      else if (r.opened) toast(r.how === "project" ? `Opening version ${r.revision} in FilmCraft as a project.` :
        `Opening version ${r.revision} in FilmCraft. It imports the timeline and captions.`);
      else if (!r.installed) toast("FilmCraft is not installed on this computer yet. The timeline is saved; get FilmCraft and try again.", true);
      else toast(`The FilmCraft project is ready: ${r.project}`);
      if (r.warnings.length) toast(r.warnings[0], true);
      setSt(await studio.filmcraft());
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
  };

  const local = st?.available !== false;
  return (
    <section className="panel" aria-labelledby="vr-finish"><h2 id="vr-finish">Finish in FilmCraft</h2>
      <p className="small muted">Hand-edit version {rev || "…"} in FilmCraft, the free open-source video editor from the
        ArtCraft team (colour, keyframes, titles and mixing). ClipForge hands it the cut as a timeline with captions; nothing
        is uploaded.</p>
      {!local && st?.message && <p className="small">{st.message}</p>}
      <div className="row-actions wrap">
        {local && <button type="button" className="btn" disabled={busy || !rev} onClick={() => void open(false)}>
          <Icon name="external" />Open in FilmCraft</button>}
        {local && <button type="button" className="btn btn-small" disabled={busy || !rev} onClick={() => void open(true)}>
          <Icon name="folder" />Show the timeline files</button>}
        <a className="btn btn-small" href={`/api/studio/videos/${v.id}/timeline.zip?revision=${rev}`}>
          <Icon name="zip" />Timeline with media (.zip)</a>
      </div>
      {local && st && !st.installed && <p className="small">FilmCraft is not on this computer yet. <a className="textlink"
        href={st.page} target="_blank" rel="noreferrer">Get FilmCraft (free)</a>, install it in Applications, then press Open
        in FilmCraft.</p>}
      {st?.installed && <p className="small muted">Found FilmCraft{st.version ? ` ${st.version}` : ""}{st.cli ?
        " and its command-line tool (the cut opens as a FilmCraft project)" : ""}.</p>}
      {last && last.not_carried.length > 0 && <Disclosure summary="What to redo by hand in FilmCraft">
        <ul className="small">{last.not_carried.map((x) => <li key={x}>{x}</li>)}</ul></Disclosure>}
    </section>
  );
}
