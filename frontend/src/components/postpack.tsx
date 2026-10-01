import { useEffect, useId, useState } from "react";
import { api, Clip, errorText, PostPackage } from "../api";
import { ConfirmDialog, Icon, Pill, toast } from "./ui";

const TITLE_MAX = 100;
const CAPTION_MAX = 2200;

export type PostDraft = Partial<PostPackage>;

/** The editable part of a post package, as the backend accepts it in a clip PATCH (`post`). */
export function postPatch(pkg: PostDraft) {
  const { titles, recommended_title, captions, hashtags, description, cta, hook, title, caption } = pkg;
  return { titles, recommended_title, captions, hashtags, description, cta, hook, title, caption };
}

export const hasPostText = (pkg: PostDraft) => !!(pkg.titles?.length || pkg.title);

function Counter({ n, max, id }: { n: number; max: number; id: string }) {
  return (
    <span id={id} className={`hint tnum ${n > max ? "bad-text" : ""}`}>{n}/{max}{n > max ? " (too long)" : ""}</span>
  );
}

function Checks({ notes }: { notes?: string[] }) {
  if (!notes?.length) return null;
  return (
    <p className="tiny warn-text">
      <Icon name="alert" className="xs" /> Not found in the clip: {notes.join("; ")}. Fine if you meant it: it is
      your text.
    </p>
  );
}

/**
 * The post text fields (controlled): title, caption, hashtags, description, call to action and hook text, with the
 * suggestions written from the clip's own words. A page saves them with its other changes.
 */
export function PostTextFields({ pkg, onChange, onUseHook }: {
  pkg: PostDraft;
  onChange: (patch: PostDraft) => void;
  onUseHook?: (hook: string) => void;
}) {
  const id = useId();
  const titles = pkg.titles || [];
  const captions = pkg.captions || [];
  // Hashtags are typed as text; keeping the text lets a space separate tags while typing.
  const [tagText, setTagText] = useState((pkg.hashtags || []).join(" "));
  useEffect(() => {
    setTagText((pkg.hashtags || []).join(" "));
  }, [pkg.generated_at]); // eslint-disable-line react-hooks/exhaustive-deps
  const titleLen = (pkg.title || "").length;
  const captionLen = (pkg.caption || "").length;

  return (
    <div className="stack-4">
      {titles.length > 0 && (
        <fieldset>
          <legend className="label">Title suggestions</legend>
          {titles.map((t, i) => (
            <label key={i} className="hook-opt">
              <input type="radio" name={`${id}-title`} checked={pkg.title === t}
                onChange={() => onChange({ title: t })} />
              <span className="small">
                {t}{i === pkg.recommended_title && <> <Pill tone="accent" icon="spark">Suggested</Pill></>}
              </span>
            </label>
          ))}
        </fieldset>
      )}
      <div className="field">
        <label htmlFor={`${id}-t`}>Title <Counter n={titleLen} max={TITLE_MAX} id={`${id}-tc`} /></label>
        <input id={`${id}-t`} type="text" value={pkg.title || ""} aria-invalid={titleLen > TITLE_MAX || undefined}
          aria-describedby={`${id}-tc`} onChange={(e) => onChange({ title: e.target.value })} />
        <Checks notes={pkg.checks?.title} />
      </div>

      {captions.length > 0 && (
        <fieldset>
          <legend className="label">Caption suggestions</legend>
          {captions.map((c, i) => (
            <label key={i} className="hook-opt">
              <input type="radio" name={`${id}-cap`} checked={pkg.caption === c}
                onChange={() => onChange({ caption: c })} />
              <span className="small">{c}</span>
            </label>
          ))}
        </fieldset>
      )}
      <div className="field">
        <label htmlFor={`${id}-c`}>Caption <Counter n={captionLen} max={CAPTION_MAX} id={`${id}-cc`} /></label>
        <textarea id={`${id}-c`} rows={4} value={pkg.caption || ""} aria-invalid={captionLen > CAPTION_MAX || undefined}
          aria-describedby={`${id}-cc`} onChange={(e) => onChange({ caption: e.target.value })} />
        <Checks notes={pkg.checks?.caption} />
      </div>

      <div className="field">
        <label htmlFor={`${id}-h`}>Hashtags <span className="hint">separated by spaces</span></label>
        <input id={`${id}-h`} type="text" value={tagText} onChange={(e) => {
          setTagText(e.target.value);
          onChange({
            hashtags: e.target.value.split(/[\s,]+/).filter(Boolean).map((t) => (t.startsWith("#") ? t : `#${t}`)),
          });
        }} />
        <Checks notes={pkg.checks?.hashtags} />
      </div>

      <div className="field">
        <label htmlFor={`${id}-d`}>Short description</label>
        <textarea id={`${id}-d`} rows={2} value={pkg.description || ""}
          onChange={(e) => onChange({ description: e.target.value })} />
        <Checks notes={pkg.checks?.description} />
      </div>

      <div className="field">
        <label htmlFor={`${id}-a`}>Call to action <span className="hint">asks viewers to do something</span></label>
        <div className="row wrap">
          <input id={`${id}-a`} type="text" className="grow" style={{ flex: "1 1 200px", width: "auto" }}
            value={pkg.cta || ""} onChange={(e) => onChange({ cta: e.target.value })} />
          <button type="button" className="btn btn-small"
            disabled={!pkg.cta || (pkg.caption || "").includes(pkg.cta || "")}
            onClick={() => onChange({ caption: `${(pkg.caption || "").trim()} ${pkg.cta}`.trim() })}>
            Add to caption
          </button>
        </div>
      </div>

      <div className="field">
        <label htmlFor={`${id}-k`}>Hook text</label>
        <div className="row wrap">
          <input id={`${id}-k`} type="text" style={{ flex: "1 1 200px", width: "auto" }} value={pkg.hook || ""}
            onChange={(e) => onChange({ hook: e.target.value })} />
          {onUseHook && (
            <button type="button" className="btn btn-small" disabled={!pkg.hook}
              onClick={() => onUseHook(pkg.hook || "")}>
              Use as on-screen hook
            </button>
          )}
        </div>
        <Checks notes={pkg.checks?.hook} />
      </div>

      <p className="hint">
        Suggestions come only from this clip's own words: no invented facts, names, numbers or claims. What you type is
        kept as you wrote it, with a note if it adds something the clip doesn't say. Nothing is posted from here.
      </p>
    </div>
  );
}

/** Replaces the post text with new suggestions from the transcript, after saying so. */
export function RewritePostDialog({ clip, edited, onClose, onDone }: {
  clip: Clip; edited: boolean; onClose: () => void; onDone: (c: Clip) => void;
}) {
  return (
    <ConfirmDialog title="Write new suggestions?" confirmLabel="Write new suggestions" onClose={onClose}
      onConfirm={async () => {
        const c = await api.regeneratePost(clip.id);
        onDone(c);
        toast("New post text written from the clip's words");
      }}>
      <p className="muted">
        ClipFoundry writes new titles, captions, hashtags, a description and a hook from this clip's own words.
      </p>
      {edited && <p className="small"><b>Your edited post text is replaced.</b> The video doesn't change.</p>}
    </ConfirmDialog>
  );
}

/**
 * Post text on its own, with its own Save: titles, captions, hashtags... written from the clip's own transcript.
 * (The clip editor uses PostTextFields and saves them with the rest of its changes.)
 */
export function PostPackageEditor({ clip, onSaved, onUseHook }: {
  clip: Clip;
  onSaved: (c: Clip) => void;
  onUseHook?: (hook: string) => void;
}) {
  const [pkg, setPkg] = useState<PostDraft>(clip.post || {});
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  useEffect(() => {
    setPkg(clip.post || {});
    setDirty(false);
  }, [clip.id, clip.post?.generated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    setBusy(true);
    try {
      const c = await api.patchClip(clip.id, { post: postPatch(pkg) });
      onSaved(c);
      setDirty(false);
      toast("Post text saved");
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Post text</h2>
        {pkg.source && <span className="tiny faint">{pkg.source}{pkg.edited ? " · edited" : ""}</span>}
      </div>
      {hasPostText(pkg) ? (
        <PostTextFields pkg={pkg} onUseHook={onUseHook} onChange={(patch) => {
          setPkg((p) => ({ ...p, ...patch }));
          setDirty(true);
        }} />
      ) : (
        <p className="muted small">
          Titles, captions, hashtags, a short description, a call to action and hook text, written only from this
          clip's words.
        </p>
      )}
      <div className="row wrap" style={{ justifyContent: "flex-end" }}>
        <button type="button" className="btn btn-quiet" disabled={busy} onClick={() => setAsking(true)}>
          <Icon name="refresh" />{hasPostText(pkg) ? "Write new suggestions…" : "Write post text…"}
        </button>
        {hasPostText(pkg) && (
          <button type="button" className="btn btn-primary" disabled={busy || !dirty} onClick={save}>
            <Icon name="check" />Save post text
          </button>
        )}
      </div>
      {asking && (
        <RewritePostDialog clip={clip} edited={!!pkg.edited || dirty} onClose={() => setAsking(false)}
          onDone={(c) => onSaved(c)} />
      )}
    </section>
  );
}
