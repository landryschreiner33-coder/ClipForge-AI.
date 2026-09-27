import { useEffect, useState } from "react";
import { api, Clip, PostPackage } from "../api";
import { Icon, toast } from "./ui";

const TITLE_MAX = 100;
const CAPTION_MAX = 2200;

function Counter({ n, max }: { n: number; max: number }) {
  return <span className={`small ${n > max ? "bad-text" : "muted"}`}>{n}/{max}</span>;
}

function Checks({ notes }: { notes?: string[] }) {
  if (!notes?.length) return null;
  return <div className="small warn-text">Not found in the clip: {notes.join("; ")}. Fine if intended; it is your text.</div>;
}

/**
 * Edit every generated field before publishing. The generated text only uses the clip's own words; what you type
 * is saved as-is (a note appears if it adds numbers, names or claims the clip does not contain).
 */
export function PostPackageEditor({ clip, onSaved, onUseHook }: {
  clip: Clip;
  onSaved: (c: Clip) => void;
  onUseHook?: (hook: string) => void;
}) {
  const [pkg, setPkg] = useState<Partial<PostPackage>>(clip.post || {});
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setPkg(clip.post || {});
    setDirty(false);
  }, [clip.id, clip.post?.generated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (patch: Partial<PostPackage>) => {
    setPkg((p) => ({ ...p, ...patch }));
    setDirty(true);
  };
  const titles = pkg.titles || [];
  const captions = pkg.captions || [];

  const save = async () => {
    setBusy(true);
    try {
      const { titles, recommended_title, captions, hashtags, description, cta, hook, title, caption } = pkg;
      const c = await api.patchClip(clip.id, {
        post: { titles, recommended_title, captions, hashtags, description, cta, hook, title, caption },
      });
      onSaved(c);
      setDirty(false);
      toast("Post package saved");
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  const regenerate = async () => {
    if ((pkg.edited || dirty) && !window.confirm("Write a new post package from the clip's transcript? Your edits to it are replaced.")) return;
    setBusy(true);
    try {
      const c = await api.regeneratePost(clip.id);
      onSaved(c);
      toast("New post package written from the transcript");
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };

  if (!titles.length && !pkg.title) {
    return (
      <div className="card">
        <h3>Post package</h3>
        <p className="muted small">Titles, captions, hashtags, a short description, a call to action and hook text, written only from this clip's transcript.</p>
        <button className="btn primary" disabled={busy} onClick={regenerate}><Icon name="spark" size={16} /> {busy ? "Writing..." : "Generate post package"}</button>
      </div>
    );
  }

  return (
    <div className="card postpack">
      <div className="row between">
        <h3 style={{ margin: 0 }}>Post package</h3>
        <span className="small muted">{pkg.source}{pkg.edited ? " · edited" : ""}</span>
      </div>

      <div className="pp-label">Title <span className="muted small">pick an option or write your own</span></div>
      <div className="grid" style={{ gap: 6 }}>
        {titles.map((t, i) => (
          <label key={i} className={`hook-opt ${pkg.title === t ? "on" : ""}`}>
            <input type="radio" checked={pkg.title === t} onChange={() => set({ title: t })} />
            <input type="text" value={t} onChange={(e) => {
              const next = [...titles];
              next[i] = e.target.value;
              set({ titles: next, ...(pkg.title === t ? { title: e.target.value } : {}) });
            }} />
            {i === pkg.recommended_title && <span className="badge good">Recommended</span>}
          </label>
        ))}
      </div>
      <label className="field mt-s">
        <span className="row between">Title used for publishing <Counter n={(pkg.title || "").length} max={TITLE_MAX} /></span>
        <input type="text" value={pkg.title || ""} onChange={(e) => set({ title: e.target.value })} />
      </label>
      <Checks notes={pkg.checks?.title} />

      <div className="pp-label mt">Caption / description</div>
      <div className="grid" style={{ gap: 6 }}>
        {captions.map((c, i) => (
          <label key={i} className={`hook-opt ${pkg.caption === c ? "on" : ""}`}>
            <input type="radio" checked={pkg.caption === c} onChange={() => set({ caption: c })} />
            <textarea rows={2} value={c} onChange={(e) => {
              const next = [...captions];
              next[i] = e.target.value;
              set({ captions: next, ...(pkg.caption === c ? { caption: e.target.value } : {}) });
            }} />
          </label>
        ))}
      </div>
      <label className="field mt-s">
        <span className="row between">Caption used for publishing <Counter n={(pkg.caption || "").length} max={CAPTION_MAX} /></span>
        <textarea rows={3} value={pkg.caption || ""} onChange={(e) => set({ caption: e.target.value })} />
      </label>
      <Checks notes={pkg.checks?.caption} />

      <label className="field mt">Hashtags
        <input type="text" value={(pkg.hashtags || []).join(" ")}
          onChange={(e) => set({ hashtags: e.target.value.split(/[\s,]+/).filter(Boolean).map((t) => (t.startsWith("#") ? t : `#${t}`)) })} />
      </label>
      <Checks notes={pkg.checks?.hashtags} />

      <label className="field mt">Short description
        <textarea rows={2} value={pkg.description || ""} onChange={(e) => set({ description: e.target.value })} />
      </label>
      <Checks notes={pkg.checks?.description} />

      <div className="grid grid-2 mt">
        <label className="field">Call to action
          <div className="row">
            <input type="text" value={pkg.cta || ""} onChange={(e) => set({ cta: e.target.value })} />
            <button className="btn sm" type="button" disabled={!pkg.cta || (pkg.caption || "").includes(pkg.cta || "")}
              onClick={() => set({ caption: `${(pkg.caption || "").trim()} ${pkg.cta}`.trim() })}>Add to caption</button>
          </div>
        </label>
        <label className="field">Hook text
          <div className="row">
            <input type="text" value={pkg.hook || ""} onChange={(e) => set({ hook: e.target.value })} />
            {onUseHook && <button className="btn sm" type="button" disabled={!pkg.hook} onClick={() => onUseHook(pkg.hook || "")}>Use on screen</button>}
          </div>
        </label>
      </div>
      <Checks notes={pkg.checks?.hook} />

      <div className="field-hint mt">
        Generated text only uses words from this clip: no invented facts, names, numbers or claims. The call to action is
        a suggestion that asks viewers to do something. Nothing is posted until you press a Publish button.
      </div>
      <div className="row mt" style={{ justifyContent: "flex-end" }}>
        <button className="btn ghost" disabled={busy} onClick={regenerate}><Icon name="refresh" size={14} /> Regenerate</button>
        <button className="btn primary" disabled={busy || !dirty} onClick={save}><Icon name="check" size={16} /> Save post package</button>
      </div>
    </div>
  );
}
