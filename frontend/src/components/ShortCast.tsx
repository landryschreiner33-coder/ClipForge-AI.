/**
 * Characters and places of an animated short (makers/cast.py): the Characters panel above the scenes, and what each
 * scene shows of them (who is in the shot, changes for that shot only, the look check). A short keeps its own copy of
 * each character; Save to library keeps it for other shorts.
 */
import { FormEvent, useEffect, useId, useRef, useState } from "react";
import { errorText } from "../api";
import {
  CastField, CastFields, CastKind, CastMember, CastOptions, CastProposal, ShortOptions, ShortScene, ShortView, shorts,
} from "../shorts";
import type { Video } from "../studio";
import { FileDrop, Picked, useUploadsByFile } from "./studioParts";
import { Banner, ConfirmDialog, Icon, Pill, toast } from "./ui";

type Run = (call: () => Promise<Video>, said?: string) => Promise<Video | null>;
const FIELD_HINTS: Record<CastField, string> = {
  appearance: "Age, face, hair, build, species",
  clothing: "What they wear",
  colors: "The colours that make them recognisable",
  props: "What they carry, or what is there",
};
const PICTURES = "image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp";
const isPicture = (f: File) => (f.type ? /^image\/(png|jpeg|webp)$/.test(f.type) : /\.(png|jpe?g|webp)$/i.test(f.name));
const thumb = (id: string) => `/api/assets/${encodeURIComponent(id)}/thumbnail`;

function labelOf(opts: CastOptions, kind: CastKind, f: CastField) {
  return opts.labels[kind]?.[f] || f;
}

/** Calls onAsset once for each picture the owner drops (a dropped file that is not a picture is refused). */
function PictureDrop({ label, onAsset }: { label: string; onAsset: (assetId: string, uploadIds: string[]) => void }) {
  const [drop, setDrop] = useState(0);
  const seen = useRef(new Set<string>());
  const uploaded = useUploadsByFile();
  const picked = (rows: Picked[]) => {
    for (const r of rows) {
      const k = `${drop}|${r.key}|${r.asset?.upload_id || ""}`;
      const wrong = !isPicture(r.file) || (!!r.asset && r.asset.kind !== "image");
      if (seen.current.has(k) || (!wrong && !r.asset)) continue;
      seen.current.add(k);
      const id = r.asset?.id || "";
      window.setTimeout(() => {
        if (wrong) {
          setDrop((n) => n + 1);
          toast("That file is not a picture. Use a PNG, JPEG or WebP picture.", true);
        } else {
          onAsset(id, uploaded.of([id]));
          setDrop((n) => n + 1);
        }
      }, 0);
      return;
    }
  };
  return <FileDrop key={drop} accept={PICTURES} label={label} onAssets={picked} onUploaded={uploaded.add} />;
}

/** The details form for a new character or a change to one: each detail can be locked. */
function MemberForm({ opts, initial, kind, saveLabel, busy, withSave, onSave, onCancel }: {
  opts: CastOptions; initial?: CastMember; kind: CastKind; saveLabel: string; busy: boolean; withSave?: boolean;
  onSave: (fields: CastFields, save: boolean) => Promise<boolean>; onCancel: () => void;
}) {
  const ids = useId();
  const [name, setName] = useState(initial?.name ?? "");
  const [values, setValues] = useState<Record<CastField, string>>({
    appearance: initial?.appearance ?? "", clothing: initial?.clothing ?? "", colors: initial?.colors ?? "",
    props: initial?.props ?? "",
  });
  const [locked, setLocked] = useState<string[]>(initial?.locked ?? []);
  const [save, setSave] = useState(true);
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => first.current?.focus(), []);
  const fields = opts.fields[kind];
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      toast(kind === "place" ? "Give the place a name." : "Give the character a name.", true);
      return;
    }
    const body: CastFields = { kind, name: name.trim(), locked: locked as CastMember["locked"] };
    for (const f of fields) body[f] = values[f].trim();
    if (await onSave(body, save)) onCancel();
  };
  const toggle = (f: string) => setLocked((l) => (l.includes(f) ? l.filter((x) => x !== f) : [...l, f]));
  return (
    <form className="cast-form stack-3" onSubmit={(e) => void submit(e)}>
      <label className="field"><span>Name</span>
        <input ref={first} type="text" value={name} maxLength={opts.max_name} onChange={(e) => setName(e.target.value)}
          placeholder={kind === "place" ? "The old lighthouse" : "Mia"} /></label>
      {fields.map((f) => (
        <div className="field cast-field" key={f}>
          <label htmlFor={`${ids}-${f}`}>{labelOf(opts, kind, f)}</label>
          <div className="cast-field-row">
            <input id={`${ids}-${f}`} type="text" value={values[f]} maxLength={opts.max_field}
              placeholder={FIELD_HINTS[f]} onChange={(e) => setValues((v) => ({ ...v, [f]: e.target.value }))} />
            <button type="button" className={`btn btn-small btn-icon cast-lock${locked.includes(f) ? " on" : ""}`}
              aria-pressed={locked.includes(f)} title={locked.includes(f) ? "Locked: a change in words never touches it"
                : "Lock this detail"} aria-label={`Lock ${labelOf(opts, kind, f).toLowerCase()}`}
              onClick={() => toggle(f)}><Icon name="lock" /></button>
          </div>
        </div>
      ))}
      <label className="choice">
        <input type="checkbox" checked={locked.includes("references")} onChange={() => toggle("references")} />
        <span>Lock the reference pictures</span></label>
      {withSave && (
        <label className="choice">
          <input type="checkbox" checked={save} onChange={(e) => setSave(e.target.checked)} />
          <span>Also keep {kind === "place" ? "this place" : "this character"} in my library for other shorts</span>
        </label>
      )}
      <div className="row">
        <button type="submit" className="btn btn-primary btn-small" disabled={busy}>{saveLabel}</button>
        <button type="button" className="btn btn-small btn-quiet" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

/** A change in the owner's own words: ClipForge AI proposes the details, the owner applies them to one shot or all. */
function ChangeInWords({ m, v, s, opts, writer, off, run, onClose }: {
  m: CastMember; v: Video; s: ShortView; opts: CastOptions; writer: ShortOptions["writer"]; off: boolean; run: Run;
  onClose: () => void;
}) {
  const ids = useId();
  const [words, setWords] = useState("");
  const [shot, setShot] = useState("");
  const [asking, setAsking] = useState(false);
  const [proposal, setProposal] = useState<CastProposal | null>(null);
  const shots = s.scenes.filter((x) => (x.cast ?? []).includes(m.id));
  const scene = shots.find((x) => x.id === shot);
  const ask = async (e: FormEvent) => {
    e.preventDefault();
    if (!words.trim()) return;
    setAsking(true);
    setProposal(null);
    try {
      setProposal(await shorts.castPropose(v.id, m.id, words.trim(), shot || undefined));
    } catch (err) {
      toast(errorText(err), true);
    } finally {
      setAsking(false);
    }
  };
  const apply = async (sceneId?: string) => {
    if (!proposal) return;
    const where = sceneId ? `shot ${s.scenes.find((x) => x.id === sceneId)?.n}` : "every shot";
    let changed = true;
    const got = await run(async () => {
      const r = await shorts.castApply(v.id, m.id, proposal.changes, sceneId);
      changed = r.applied.changed.length > 0;
      return r;
    });
    if (!got) return;
    toast(changed ? `${m.name} changed in ${where}. ClipForge makes those pictures again.`
      : `Nothing changed: ${m.name} already looks like that in ${where}.`);
    onClose();
  };
  if (!writer.configured) {
    return (
      <Banner tone="info" icon="spark" title="Changes in your own words need ClipForge AI">
        Set it up in <a href="#/settings/ai">Settings → ClipForge AI</a>, or press Edit to change the details yourself.
      </Banner>
    );
  }
  const changed = proposal ? (Object.keys(proposal.changes) as CastField[]) : [];
  return (
    <div className="cast-change stack-3">
      <form className="stack-2" onSubmit={(e) => void ask(e)}>
        <label className="field"><span>What should change?</span>
          <textarea rows={2} value={words} maxLength={opts.max_change} disabled={asking}
            placeholder={m.kind === "place" ? "Make it night, with snow on the roof" : "Give her a blue raincoat"}
            onChange={(e) => setWords(e.target.value)} /></label>
        <div className="row">
          <label className="field cast-shot" htmlFor={`${ids}-shot`}><span className="sr-only">Start from</span>
            <select id={`${ids}-shot`} value={shot} onChange={(e) => setShot(e.target.value)}>
              <option value="">{m.name} as in every shot</option>
              {shots.map((x) => <option key={x.id} value={x.id}>{m.name} as in shot {x.n}</option>)}
            </select></label>
          <button type="submit" className="btn btn-small" disabled={asking || off || !words.trim()}>
            {asking ? <><span className="inline-spinner" aria-hidden="true" />Asking {writer.label}…</>
              : <><Icon name="spark" />Show the changes</>}</button>
          <button type="button" className="btn btn-small btn-quiet" onClick={onClose}>Cancel</button>
        </div>
      </form>
      {proposal && (
        <div className="cast-proposal" role="status">
          <b>{changed.length ? "Proposed changes" : "Nothing to change"}</b>
          {changed.length > 0 && (
            <dl className="cast-diff">
              {changed.map((f) => (
                <div key={f}><dt>{labelOf(opts, m.kind, f)}</dt>
                  <dd><s className="muted">{(scene ? { ...m, ...(scene.overrides?.[m.id] ?? {}) } : m)[f] || "—"}</s>
                    <Icon name="arrow" className="sm" /><span>{proposal.changes[f]}</span></dd></div>
              ))}
            </dl>
          )}
          {proposal.note && <p className="small muted">{proposal.note}</p>}
          {changed.length > 0 && (
            <div className="row">
              <button type="button" className="btn btn-primary btn-small" disabled={off}
                onClick={() => void apply()}>Apply to every shot</button>
              {shots.map((x) => (x.id === shot || shots.length <= 4) && (
                <button key={x.id} type="button" className="btn btn-small" disabled={off}
                  onClick={() => void apply(x.id)}>Shot {x.n} only</button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MemberCard({ m, v, s, opts, writer, off, run }: {
  m: CastMember; v: Video; s: ShortView; opts: CastOptions; writer: ShortOptions["writer"]; off: boolean; run: Run;
}) {
  const [mode, setMode] = useState<"" | "edit" | "words" | "refs">("");
  const [removing, setRemoving] = useState(false);
  const [busy, setBusy] = useState(false);
  const shots = s.scenes.filter((x) => (x.cast ?? []).includes(m.id));
  const withPictures = s.scenes.filter((x) => x.picture_asset_id && x.picture_source !== "upload");
  const refsLocked = m.locked.includes("references");
  const save = async (fields: CastFields) => {
    setBusy(true);
    const got = await run(() => shorts.castChange(v.id, m.id, fields), `${fields.name || m.name} saved.`);
    setBusy(false);
    return !!got;
  };
  const setRefs = (refs: string[], said: string) => run(() => shorts.castChange(v.id, m.id, { refs }), said);
  const avatar = m.refs.find((r) => r.ok);
  return (
    <li className="cast-card">
      <div className="cast-top">
        {avatar ? <img className="cast-avatar" src={thumb(avatar.asset_id)} alt="" />
          : <span className="cast-avatar letter" aria-hidden="true">{m.name.slice(0, 1).toUpperCase()}</span>}
        <div className="grow">
          <h3 className="cast-name">{m.name} <Pill tone="info">{m.kind === "place" ? "Place" : "Character"}</Pill>
            {m.locked.length > 0 && <span className="small muted"><Icon name="lock" className="sm" />
              {m.locked.length} locked</span>}</h3>
          <p className="small cast-described">{m.described}</p>
          <p className="small muted">
            {shots.length === s.scenes.length ? "In every shot" : shots.length ? `In shots ${shots.map((x) => x.n)
              .join(", ")}` : "In no shot yet"}
            {" · "}{m.refs.length ? `${m.refs.length} reference picture${m.refs.length === 1 ? "" : "s"}`
              : "No reference picture"}
            {m.library === "same" && " · In your library"}
            {m.library === "differs" && " · Changed here since it was saved to your library"}
          </p>
        </div>
      </div>
      <div className="row cast-actions">
        <button type="button" className="btn btn-small" aria-expanded={mode === "edit"} disabled={off}
          onClick={() => setMode(mode === "edit" ? "" : "edit")}><Icon name="edit" />Edit</button>
        <button type="button" className="btn btn-small" aria-expanded={mode === "words"} disabled={off}
          onClick={() => setMode(mode === "words" ? "" : "words")}><Icon name="spark" />Describe a change</button>
        <button type="button" className="btn btn-small" aria-expanded={mode === "refs"} disabled={off}
          onClick={() => setMode(mode === "refs" ? "" : "refs")}><Icon name="image" />Reference pictures</button>
        {m.library !== "same" && (
          <button type="button" className="btn btn-small btn-quiet" disabled={off}
            onClick={() => void run(() => shorts.castToLibrary(v.id, m.id), `${m.name} is saved in your library.`)}>
            <Icon name="star" />{m.library === "differs" ? "Update in library" : "Save to library"}</button>
        )}
        <button type="button" className="btn btn-small btn-quiet" disabled={off} onClick={() => setRemoving(true)}>
          <Icon name="trash" />Remove</button>
      </div>
      {mode === "edit" && (
        <MemberForm opts={opts} initial={m} kind={m.kind} saveLabel="Save the changes" busy={busy || off}
          onSave={(fields) => save(fields)} onCancel={() => setMode("")} />
      )}
      {mode === "words" && (
        <ChangeInWords m={m} v={v} s={s} opts={opts} writer={writer} off={off} run={run} onClose={() => setMode("")} />
      )}
      {mode === "refs" && (
        <div className="cast-refs stack-3">
          <p className="small muted">{s.engines.image.references
            ? "Your picture maker draws every shot with these pictures, so the look stays the same."
            : "Your picture maker keeps the look from the written details; these pictures are kept for a picture "
              + "maker that takes reference pictures (FLUX.2 klein)."}</p>
          {m.refs.length > 0 && (
            <ul className="cast-ref-list">
              {m.refs.map((r, k) => (
                <li key={r.asset_id}>
                  {r.ok ? <img src={thumb(r.asset_id)} alt={`Reference picture ${k + 1} of ${m.name}`} />
                    : <span className="cast-ref-gone">Missing</span>}
                  <button type="button" className="btn btn-small btn-quiet" disabled={off || refsLocked}
                    onClick={() => void setRefs(m.refs.filter((x) => x.asset_id !== r.asset_id).map((x) => x.asset_id),
                      `A reference picture of ${m.name} was removed.`)}>Remove</button>
                </li>
              ))}
            </ul>
          )}
          {refsLocked ? <p className="small muted"><Icon name="lock" className="sm" />The reference pictures are
            locked. Unlock them under Edit to change them.</p>
            : m.refs.length >= opts.max_refs ? <p className="small muted">{m.name} has {opts.max_refs} reference
              pictures, the most a character keeps. Remove one to add another.</p> : (
              <>
                <PictureDrop label={`Drop a PNG, JPEG or WebP picture of ${m.name}`}
                  onAsset={(id, uploads) => void run(() => shorts.castReference(v.id, m.id, { asset_id: id,
                    upload_ids: uploads }), `The picture is now a reference of ${m.name}.`)} />
                {withPictures.length > 0 && (
                  <div className="stack-2">
                    <span className="label small">Or use a shot's picture</span>
                    <ul className="cast-ref-list">
                      {withPictures.slice(0, 12).map((x) => (
                        <li key={x.id}>
                          <button type="button" className="scene-earlier-btn" disabled={off}
                            aria-label={`Use the picture of shot ${x.n} as a reference of ${m.name}`}
                            onClick={() => void run(() => shorts.castReference(v.id, m.id, { scene_id: x.id }),
                              `The picture of shot ${x.n} is now a reference of ${m.name}.`)}>
                            <img src={thumb(x.picture_asset_id)} alt="" loading="lazy" /></button>
                          <span className="small muted">Shot {x.n}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}
        </div>
      )}
      {removing && (
        <ConfirmDialog title={`Take ${m.name} out of this short?`} confirmLabel="Take out" onClose={() => setRemoving(false)}
          onConfirm={() => run(() => shorts.castRemove(v.id, m.id), `${m.name} was taken out of the short.`)}>
          <p className="muted">The pictures {m.name} is in are made again without {m.kind === "place" ? "it" : "them"}.
            {m.library === "same" || m.library === "differs" ? ` ${m.name} stays in your library.` : ""}</p>
        </ConfirmDialog>
      )}
    </li>
  );
}

/** The Characters panel: the short's characters and places, adding new ones or ones from the library. */
export function CastPanel({ v, s, opts, off, run }: {
  v: Video; s: ShortView; opts: ShortOptions | null; off: boolean; run: Run;
}) {
  const head = useId();
  const [adding, setAdding] = useState<"" | CastKind | "library">("");
  const [library, setLibrary] = useState<CastMember[] | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [forgetting, setForgetting] = useState<CastMember | null>(null);
  const cast = s.cast ?? [];
  useEffect(() => {
    if (adding !== "library") return;
    setProblem("");
    shorts.library().then((r) => setLibrary(r.library)).catch((e) => setProblem(errorText(e)));
  }, [adding]);
  if (!opts?.cast) return null;
  const co = opts.cast;
  const full = cast.length >= co.max_cast;
  const inShort = new Set(cast.map((m) => m.library_id).filter(Boolean));
  const add = async (fields: CastFields, save: boolean) => {
    setBusy(true);
    const got = await run(() => shorts.castAdd(v.id, { ...fields, save }),
      `${fields.name} is in the short. ClipForge makes the pictures again with ${fields.kind === "place" ? "it" : "them"}.`);
    setBusy(false);
    return !!got;
  };
  return (
    <section className="panel short-cast" aria-labelledby={head}>
      <div className="panel-head">
        <h2 id={head}>Characters and places ({cast.length})</h2>
        {!s.engines.image.ready ? <Pill>Pictures are designed cards</Pill>
          : s.engines.image.references ? <Pill tone="good" icon="image">Uses reference pictures</Pill>
            : <Pill icon="edit">Keeps them by their description</Pill>}
      </div>
      <p className="small muted">Who and where the pictures show. Every shot shows them unless you choose who is in a
        shot. Lock a detail so a change in words never touches it.</p>
      {cast.length > 0 && (
        <ul className="cast-list">
          {cast.map((m) => <MemberCard key={m.id} m={m} v={v} s={s} opts={co} writer={opts.writer} off={off}
            run={run} />)}
        </ul>
      )}
      {cast.length === 0 && s.character && (
        <p className="small muted">ClipForge AI drew the main character as: “{s.character}”. Add a character to keep
          them the same in every shot.</p>
      )}
      {full ? <p className="small muted">A short has at most {co.max_cast} characters and places.</p> : (
        <div className="row wrap">
          <button type="button" className="btn btn-small" aria-expanded={adding === "character"} disabled={off}
            onClick={() => setAdding(adding === "character" ? "" : "character")}><Icon name="plus" />Add a character
          </button>
          <button type="button" className="btn btn-small" aria-expanded={adding === "place"} disabled={off}
            onClick={() => setAdding(adding === "place" ? "" : "place")}><Icon name="plus" />Add a place</button>
          <button type="button" className="btn btn-small" aria-expanded={adding === "library"} disabled={off}
            onClick={() => setAdding(adding === "library" ? "" : "library")}><Icon name="layers" />From my library
          </button>
        </div>
      )}
      {(adding === "character" || adding === "place") && (
        <MemberForm opts={co} kind={adding} withSave busy={busy || off}
          saveLabel={adding === "place" ? "Add the place" : "Add the character"}
          initial={adding === "character" && s.character && !cast.length
            ? { appearance: s.character } as CastMember : undefined}
          onSave={add} onCancel={() => setAdding("")} />
      )}
      {adding === "library" && (
        <div className="stack-2">
          {problem && <p className="error-text"><Icon name="alert" className="sm" />{problem}</p>}
          {!library && !problem && <p className="small muted">Loading your library…</p>}
          {library && library.length === 0 && <p className="small muted">Your library is empty. Characters you add
            are kept there for your other shorts.</p>}
          {library && library.length > 0 && (
            <ul className="cast-library">
              {library.map((m) => (
                <li key={m.id}>
                  <div className="grow"><b>{m.name}</b> <span className="small muted">{m.kind === "place" ? "Place"
                    : "Character"}</span><p className="small muted">{m.described}</p></div>
                  <button type="button" className="btn btn-small" disabled={off || inShort.has(m.id)}
                    onClick={() => void run(() => shorts.castAdd(v.id, { library_id: m.id }),
                      `${m.name} is in the short.`).then((got) => got && setAdding(""))}>
                    {inShort.has(m.id) ? "In this short" : "Add"}</button>
                  <button type="button" className="btn btn-small btn-quiet btn-icon" disabled={off}
                    aria-label={`Delete ${m.name} from your library`} title="Delete from your library"
                    onClick={() => setForgetting(m)}><Icon name="trash" /></button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {forgetting && (
        <ConfirmDialog title={`Delete ${forgetting.name} from your library?`} confirmLabel="Delete" danger
          onClose={() => setForgetting(null)}
          onConfirm={async () => {
            await shorts.libraryDelete(forgetting.id);
            setLibrary((list) => (list ?? []).filter((x) => x.id !== forgetting.id));
            toast(`${forgetting.name} was deleted from your library.`);
          }}>
          <p className="muted">{forgetting.name}'s details go from your library. Shorts that already
            have {forgetting.kind === "place" ? "it" : "them"} keep their own copy. The reference pictures are no
            longer kept for the library: a short or video that uses them keeps them until you delete it.</p>
        </ConfirmDialog>
      )}
    </section>
  );
}

/** Who is in this shot, its changes for this shot only, and what the look check found. */
export function SceneCast({ scene, v, s, off, run }: {
  scene: ShortScene; v: Video; s: ShortView; off: boolean; run: Run;
}) {
  const cast = s.cast ?? [];
  const inShot = new Set(scene.cast ?? []);
  const label = useId();
  if (!cast.length) return null;
  const toggle = (id: string) => {
    const next = cast.filter((m) => (m.id === id ? !inShot.has(id) : inShot.has(m.id))).map((m) => m.id);
    const name = cast.find((m) => m.id === id)?.name;
    void run(() => shorts.patchScene(v.id, scene.id, { cast: next }),
      `${name} is ${inShot.has(id) ? "out of" : "in"} shot ${scene.n} now. ClipForge makes its picture again.`);
  };
  const overrides = Object.entries(scene.overrides ?? {});
  const flags = scene.drift && !scene.drift.ok ? scene.drift.flags : [];
  return (
    <div className="scene-cast stack-2">
      <div className="row scene-cast-row" role="group" aria-labelledby={label}>
        <span className="label small" id={label}>In this shot</span>
        {cast.map((m) => (
          <button key={m.id} type="button" className={`chip${inShot.has(m.id) ? " on" : ""}`} aria-pressed={inShot.has(m.id)}
            disabled={off} onClick={() => toggle(m.id)}>{inShot.has(m.id) && <Icon name="check" className="sm" />}{m.name}
          </button>
        ))}
        {scene.cast_chosen && (
          <button type="button" className="link-btn small" disabled={off}
            onClick={() => void run(() => shorts.patchScene(v.id, scene.id, { all_cast: true }),
              `Shot ${scene.n} shows everyone again.`)}>Everyone</button>
        )}
      </div>
      {overrides.map(([mid, o]) => {
        const m = cast.find((x) => x.id === mid);
        if (!m) return null;
        return (
          <p key={mid} className="small scene-override"><Icon name="edit" className="sm" />
            <span>Only in this shot: {m.name} {Object.entries(o).map(([f, val]) => `${(f === "clothing" ? "wears"
              : f === "props" ? "has" : f === "colors" ? "in" : "looks like")} ${val}`).join("; ")}.</span>
            <button type="button" className="link-btn" disabled={off}
              onClick={() => void run(() => shorts.clearOverride(v.id, scene.id, mid),
                `Shot ${scene.n} shows ${m.name} as in every shot again.`)}>Use the usual look</button></p>
        );
      })}
      {flags.length > 0 && (
        <div className="scene-drift" role="note">
          <Icon name="alert" className="sm" />
          <div className="grow">
            <b>{[...new Set(flags.map((f) => f.name))].join(" and ")} may look different here</b>
            <ul>{flags.map((f, k) => <li key={k} className="small">{f.why}{f.detail ? ` (${f.name}: ${f.detail})` : ""}
            </li>)}</ul>
          </div>
          <div className="row wrap">
            <button type="button" className="btn btn-small" disabled={off}
              onClick={() => void run(() => shorts.patchScene(v.id, scene.id, { new_picture: true }),
                `ClipForge is making shot ${scene.n} again.`)}><Icon name="refresh" />Make again</button>
            <button type="button" className="btn btn-small btn-quiet" disabled={off}
              onClick={() => void run(() => shorts.patchScene(v.id, scene.id, { drift_ok: true }),
                "Marked as looking right.")}>Looks right</button>
          </div>
        </div>
      )}
    </div>
  );
}

/** "Use this picture as a reference of …" under a scene's picture. */
export function UseAsReference({ scene, v, s, off, run }: {
  scene: ShortScene; v: Video; s: ShortView; off: boolean; run: Run;
}) {
  const who = (s.cast ?? []).filter((m) => (scene.cast ?? []).includes(m.id));
  if (!who.length || !scene.picture_asset_id || scene.picture_source === "upload") return null;
  return (
    <p className="small row scene-use-ref"><span className="muted">Use this picture as a reference of</span>
      {who.map((m) => {
        const has = m.refs.some((r) => r.asset_id === scene.picture_asset_id);
        return (
          <button key={m.id} type="button" className="btn btn-small" disabled={off || has || m.locked.includes("references")}
            onClick={() => void run(() => shorts.castReference(v.id, m.id, { scene_id: scene.id }),
              `The picture of shot ${scene.n} is now a reference of ${m.name}.`)}>{has ? `${m.name} ✓` : m.name}</button>
        );
      })}</p>
  );
}
