import { Fragment, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { api, errorText } from "../api";
import { useMotion } from "../motion";
import { useLeaveGuard } from "../router";
import { Field, Style, studio } from "../studio";
import { Banner, ConfirmDialog, Icon, toast } from "./ui";
import "./StyleStudio.css";

/* Brain → Styles in the space studio (2026-11-19): the style's choices on the left and a preview you can play on the
 * right. A style remembers only the choices that are set; everything else still comes from the project, other Brain
 * items and Settings. Saving an existing style saves a new revision (older projects keep theirs); another tab's save
 * in between is a conflict, never a lost edit. */

const MODES = ["highlights", "full_stories", "full_video"];
/** The four choices of the picture; every other editing choice is under More choices. */
const MAIN = ["aspect_ratio", "caption_style", "caption_position", "feel"];
const CHOICE_WORDS: Record<string, string> = { clean: "Clean", bold: "Bold", high_energy: "High energy", minimal: "Minimal",
  bottom: "Lower third", middle: "Middle", top: "Top", calm: "Calm", balanced: "Balanced", energetic: "Energetic" };
const word = (v: unknown) => CHOICE_WORDS[String(v)] || String(v).replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/** The caption looks the renderer burns in (pipeline/captions.py STYLE_PRESETS): sizes are for a 1080 × 1920 clip. */
const PRESETS: Record<string, { font: string; weight: number; size: number; upper: boolean; words: number; chars: number;
  outline: number; shadow: number; highlight: string; pop: boolean; shade: number }> = {
  clean: { font: "Caption Poppins", weight: 600, size: 76, upper: false, words: 5, chars: 26, outline: 5, shadow: 1,
    highlight: "#FFD23F", pop: false, shade: 0.61 },
  bold: { font: "Caption Poppins", weight: 800, size: 92, upper: true, words: 3, chars: 18, outline: 7, shadow: 3,
    highlight: "#FFE500", pop: false, shade: 0.61 },
  high_energy: { font: "Caption Anton", weight: 400, size: 132, upper: true, words: 2, chars: 14, outline: 8, shadow: 4,
    highlight: "#3CFF6B", pop: true, shade: 0.61 },
  minimal: { font: "Caption Poppins", weight: 500, size: 62, upper: false, words: 7, chars: 34, outline: 0, shadow: 2,
    highlight: "#FFFFFF", pop: false, shade: 0.41 },
};
/** Where captions sit (share of the height from the bottom or top): clips (captions.py) and videos (studio/engine.py). */
const CLIP_PLACE: Record<string, number> = { bottom: 0.36, middle: 0, top: 0.16 };
const VIDEO_PLACE: Record<string, number> = { bottom: 0.08, middle: 0, top: 0.08 };
const SAMPLE = "Keep moving. Every new clip starts closer to how you like it.".split(" ");
/** The preview's background pictures: a sunset road, 9:16 for clips and 16:9 for videos. */
const SCENE_PICTURE = { tall: "/brain/style-preview-tall.jpg", wide: "/brain/style-preview-wide.jpg" };
const SECONDS = 6;

const same = (a: Record<string, unknown>, b: Record<string, unknown>) => {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)].filter((k) => a[k] !== undefined || b[k] !== undefined));
  return [...keys].every((k) => a[k] === b[k]);
};

export function StylesTab() {
  const [rows, setRows] = useState<Style[] | null>(null);
  const [fields, setFields] = useState<Field[] | null>(null);
  const [defaults, setDefaults] = useState<{ style: string; position: string }>({ style: "bold", position: "bottom" });
  const [current, setCurrent] = useState("new");
  const [name, setName] = useState("");
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [problem, setProblem] = useState("");
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<Style | null>(null);
  const load = useCallback(() => studio.styles().then((r) => { setRows(r); return r; })
    .catch((e) => { setProblem(errorText(e)); setRows([]); return [] as Style[]; }), []);
  useEffect(() => {
    void load();
    studio.capabilities().then((c) => setFields(c.fields.filter((f) => f.kind !== "text"))).catch((e) => setProblem(errorText(e)));
    api.settings().then((s) => setDefaults({ style: String(s.caption_style || "bold"), position: String(s.caption_position || "bottom") }))
      .catch(() => undefined);  // the preview then shows the built-in defaults
  }, [load]);
  const saved = rows?.find((r) => r.id === current) || null;
  const savedKey = saved ? `${saved.id}:${saved.revision}` : "new";
  useEffect(() => {
    setName(saved?.name || "");
    setValues({ ...(saved?.values || {}) });
    setConflict(false);
    setProblem("");
  }, [savedKey]);  // eslint-disable-line react-hooks/exhaustive-deps
  const modes = saved?.modes?.length ? saved.modes : MODES;
  const applies = (f: Field) => f.modes.some((m) => modes.includes(m));
  const byName = new Map((fields || []).map((f) => [f.name, f]));
  const chosen = Object.fromEntries(Object.entries(values).filter(([k, v]) => v !== undefined && v !== ""
    && byName.has(k) && applies(byName.get(k)!)));
  const dirty = name.trim() !== (saved?.name || "") || !same(chosen, saved?.values || {});
  const set = (key: string, value: unknown) => setValues((old) => ({ ...old, [key]: value }));
  const discard = () => {
    setName(saved?.name || "");
    setValues({ ...(saved?.values || {}) });
  };
  const save = async (): Promise<boolean> => {
    setBusy(true);
    setProblem("");
    try {
      const s = saved
        ? await studio.updateStyle(saved.id, { revision: saved.revision, name: name.trim(), values: chosen })
        : await studio.createStyle({ name: name.trim(), values: chosen, modes: MODES });
      toast(saved ? `Saved “${s.name}” (revision ${s.revision}). New projects use it.` : `Saved “${s.name}”. New projects can use it.`);
      await load();
      setCurrent(s.id);
      return true;
    } catch (e) {
      const text = errorText(e);
      setProblem(text);
      setConflict(/changed elsewhere/i.test(text));
      return false;
    } finally {
      setBusy(false);
    }
  };
  const canSave = !busy && dirty && !!name.trim() && Object.keys(chosen).length > 0;
  useLeaveGuard(useMemo(() => (dirty ? { what: "this style", save, discard } : null),
    [dirty, name, values, saved?.revision]));  // eslint-disable-line react-hooks/exhaustive-deps
  // switching styles would drop the draft, so it waits for Save or Discard
  const pick = (id: string) => { if (id !== current && !dirty) setCurrent(id); };
  if (rows === null) return <p className="muted">Loading styles…</p>;
  const format = String(chosen.aspect_ratio || "9:16") === "16:9" ? "16:9" : "9:16";
  const look = String(chosen.caption_style || defaults.style);
  const place = String(chosen.caption_position || defaults.position);
  return (
    <div className="style-studio">
      <section className="style-form" aria-labelledby="style-title">
        <div className="style-head">
          <div>
            <div className="style-title-row">
              <h2 id="style-title">{saved ? saved.name : "New style"}</h2>
              <span className={`style-state ${dirty || !saved ? "draft" : "saved"}`} role="status">
                <i aria-hidden="true" />{dirty || !saved ? "Draft" : "Saved"}</span>
            </div>
            <p className="muted">{rows.length} saved style{rows.length === 1 ? "" : "s"}{saved
              ? ` · revision ${saved.revision}${saved.is_default ? " · my saved style" : ""}` : ""}</p>
          </div>
          <svg className="style-stars" viewBox="0 0 140 70" aria-hidden="true">
            <path d="M14 34H70L126 4M70 34L54 62M70 34L136 34" />
            <circle cx="14" cy="34" r="4" /><circle cx="54" cy="62" r="4" />
          </svg>
        </div>
        <nav className="style-pick" aria-label="Your styles">
          <button type="button" aria-pressed={current === "new"} disabled={dirty && current !== "new"}
            onClick={() => pick("new")}><Icon name="plus" />New style</button>
          {rows.map((r) => (
            <button key={r.id} type="button" aria-pressed={current === r.id} disabled={dirty && current !== r.id}
              onClick={() => pick(r.id)}>{r.is_default && <Icon name="check" />}{r.name}</button>
          ))}
        </nav>
        {dirty && rows.length > 0 && <p className="style-hint">Save or discard this draft to open another style.</p>}
        {problem && (
          <Banner tone={conflict ? "warn" : "bad"} title={conflict ? "Saved somewhere else first" : "Could not save the style"}
            actions={conflict ? <button type="button" className="btn btn-small" onClick={() => {
              setProblem("");
              setConflict(false);
              void load();
            }}>
              <Icon name="refresh" />Load the newest</button> : undefined}>{problem}</Banner>
        )}
        <div className="style-rows">
          <div className="style-row">
            <label htmlFor="style-name">Style name</label>
            <input id="style-name" value={name} maxLength={60} placeholder="For example: Night drive captions"
              onChange={(e) => setName(e.target.value)} />
          </div>
          {byName.get("aspect_ratio") && applies(byName.get("aspect_ratio")!) && (
            <FormatRow value={chosen.aspect_ratio as string | undefined} onChange={(v) => set("aspect_ratio", v)} />
          )}
          {(["caption_style", "caption_position", "feel"] as const).map((key) => {
            const f = byName.get(key);
            if (!f || !applies(f)) return null;
            const label = key === "caption_style" ? "Caption style" : key === "caption_position" ? "Position" : "Pacing";
            const hint = key === "caption_style" ? "The font and the colour of the word being said."
              : key === "caption_position" ? "Where captions sit on the picture." : "How lively YouTube videos feel.";
            const fallback = key === "caption_style" ? ` (Settings: ${word(defaults.style)})`
              : key === "caption_position" ? ` (Settings: ${word(defaults.position)})` : "";
            return (
              <div className="style-row" key={key}>
                <label htmlFor={`style-${key}`}>{label}</label>
                <div className="style-control">
                  <select id={`style-${key}`} value={chosen[key] === undefined ? "" : String(chosen[key])}
                    aria-describedby={`style-${key}-hint`}
                    onChange={(e) => set(key, e.target.value === "" ? undefined : f.choices.find((c) => String(c) === e.target.value))}>
                    <option value="">Not set{fallback}</option>
                    {f.choices.map((c) => <option key={String(c)} value={String(c)}>{word(c)}</option>)}
                  </select>
                  <span id={`style-${key}-hint`} className="style-hint">{hint}</span>
                </div>
              </div>
            );
          })}
        </div>
        <MoreChoices fields={(fields || []).filter((f) => !MAIN.includes(f.name) && applies(f))} values={chosen} set={set} />
        <div className="style-foot">
          <button type="button" className="btn btn-primary" disabled={!canSave} onClick={() => void save()}>
            {busy ? "Saving…" : "Save style"}</button>
          <button type="button" className="btn" disabled={!dirty || busy} onClick={discard}>Discard</button>
          <span className="style-foot-note">{!name.trim() && dirty ? "Give the style a name to save it."
            : dirty && !Object.keys(chosen).length ? "Pick at least one choice to save."
              : "Applies to new projects."}</span>
          {saved && (
            <span className="style-foot-more">
              {!saved.is_default && <button type="button" className="btn btn-small" disabled={busy}
                onClick={async () => { await studio.defaultStyle(saved.id); await load(); toast(`“${saved.name}” is now your saved style.`); }}>
                Use as my saved style</button>}
              <button type="button" className="btn btn-small btn-danger" disabled={busy} onClick={() => setDeleting(saved)}>
                <Icon name="trash" />Delete</button>
            </span>
          )}
        </div>
      </section>
      <CaptionPreview format={format} look={look} place={place} />
      {deleting && <ConfirmDialog title={`Delete “${deleting.name}”?`} danger confirmLabel="Delete style"
        onClose={() => setDeleting(null)}
        onConfirm={async () => { await studio.deleteStyle(deleting.id); setDeleting(null); setCurrent("new"); await load(); }}>
        <p>Projects that already used it keep the choices they were made with.</p></ConfirmDialog>}
    </div>
  );
}

/** 9:16 or 16:9 for YouTube videos (clips are always 9:16). Pressing the chosen one again leaves it unset. */
function FormatRow({ value, onChange }: { value?: string; onChange: (v: string | undefined) => void }) {
  const hint = useId();
  return (
    <div className="style-row">
      <span className="style-label" id={`${hint}-label`}>Format</span>
      <div className="style-control">
        <div className="style-format" role="group" aria-labelledby={`${hint}-label`} aria-describedby={hint}>
          {(["9:16", "16:9"] as const).map((v) => (
            <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(value === v ? undefined : v)}>
              <Icon name={v === "9:16" ? "phone" : "screen"} />{v}</button>
          ))}
          {value && value !== "9:16" && value !== "16:9" && <button type="button" aria-pressed="true"
            onClick={() => onChange(undefined)}>{value}</button>}
        </div>
        <span id={hint} className="style-hint">{value ? "YouTube videos get this shape; clips are always 9:16. Press it again to leave it unset."
          : "Not set: clips are 9:16 and YouTube videos keep their own shape."}</span>
      </div>
    </div>
  );
}

/** Every other editing choice a style can remember, folded away. */
function MoreChoices({ fields, values, set }: { fields: Field[]; values: Record<string, unknown>;
  set: (key: string, value: unknown) => void }) {
  const on = fields.filter((f) => values[f.name] !== undefined).length;
  return (
    <details className="style-more">
      <summary>More choices{on ? ` (${on} set)` : ""}</summary>
      <div className="style-rows">
        {fields.map((f) => (
          <div className="style-row" key={f.name}>
            <label htmlFor={`style-more-${f.name}`}>{f.label}</label>
            {f.kind === "number" ? (
              <input id={`style-more-${f.name}`} type="number" inputMode="decimal" min={f.minimum ?? undefined}
                max={f.maximum ?? undefined} placeholder="Not set"
                value={values[f.name] === undefined ? "" : String(values[f.name])}
                onChange={(e) => set(f.name, e.target.value === "" ? undefined : Number(e.target.value))} />
            ) : (
              <select id={`style-more-${f.name}`} value={values[f.name] === undefined ? "" : String(values[f.name])}
                onChange={(e) => {
                  const raw = e.target.value;
                  set(f.name, raw === "" ? undefined : f.kind === "bool" ? raw === "true" : f.choices.find((c) => String(c) === raw));
                }}>
                <option value="">Not set</option>
                {f.kind === "bool" ? <><option value="true">On</option><option value="false">Off</option></>
                  : f.choices.map((c) => <option key={String(c)} value={String(c)}>{word(c)}</option>)}
              </select>
            )}
          </div>
        ))}
      </div>
    </details>
  );
}

/** Groups of words the way the renderer splits captions: at most `words` words and `chars` letters a group. */
function groups(words: string[], most: number, chars: number): number[][] {
  const out: number[][] = [];
  let group: number[] = [], length = 0;
  words.forEach((w, i) => {
    if (group.length && (group.length >= most || length + 1 + w.length > chars)) {
      out.push(group);
      group = [];
      length = 0;
    }
    group.push(i);
    length += (length ? 1 : 0) + w.length;
  });
  if (group.length) out.push(group);
  return out;
}

/** Sample words played over a drawn night drive: the font, size, outline, highlight colour and place the renderer
 * uses for this choice. Clips light up the word being said; YouTube videos show white words (studio/engine.py). */
function CaptionPreview({ format, look, place }: { format: "9:16" | "16:9"; look: string; place: string }) {
  const p = PRESETS[look] || PRESETS.clean;
  const { pageHidden } = useMotion();
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const frame = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(0);
  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const measure = () => setHeight(el.clientHeight);
    measure();
    const seen = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    seen?.observe(el);
    return () => seen?.disconnect();
  }, [format]);
  useEffect(() => {
    if (!playing || pageHidden) return;
    let raf = 0, last = performance.now();
    const step = (now: number) => {
      const next = (now - last) / 1000;
      last = now;
      setT((old) => {
        if (old + next >= SECONDS) {
          setPlaying(false);
          return SECONDS;
        }
        return old + next;
      });
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, pageHidden]);
  const clip = format === "9:16";
  const words = SAMPLE.map((w) => (p.upper ? w.toUpperCase() : w));
  const per = SECONDS / words.length;
  const at = Math.min(words.length - 1, Math.floor(t / per));
  const shown = groups(words, p.words, p.chars).find((g) => g.includes(at)) || [];
  const px = clip ? (p.size / 1920) * height : (p.size / 1080) * height * 0.72;
  const outline = clip ? (p.outline / 1920) * height : 4 * (height / 1080);
  const shadow = clip ? (p.shadow / 1920) * height : height / 1080;
  const share = (clip ? CLIP_PLACE : VIDEO_PLACE)[place] ?? 0.36;
  const where = place === "middle" ? {} : place === "top" ? { top: `${share * 100}%` } : { bottom: `${share * 100}%` };
  const clock = (s: number) => `0:${String(Math.floor(s)).padStart(2, "0")}`;
  return (
    <section className="style-preview" aria-labelledby="style-preview-title">
      <h2 id="style-preview-title">Preview</h2>
      <div ref={frame} className={`style-frame ${clip ? "tall" : "wide"}`} role="img"
        aria-label={`Caption preview: ${word(look)} captions, ${word(place).toLowerCase()}, ${format}`}>
        {/* a sunset road behind the sample words: a photo-like picture (the owner's, 2026-11-26) over the drawn one,
            which still shows if the picture can't load */}
        <div className="style-scene" aria-hidden="true"><i className="sun" /><i className="hills" /><i className="road" />
          <img key={format} className="style-scene-picture" src={SCENE_PICTURE[clip ? "tall" : "wide"]} alt=""
            decoding="async" onError={(e) => { e.currentTarget.hidden = true; }} /></div>
        <div className={`style-caption at-${place}`} aria-hidden="true" style={{
          ...where, fontFamily: `"${p.font}", "Poppins", sans-serif`, fontWeight: p.weight, fontSize: `${px}px`,
          // the renderer's outline sits outside the letters: a stroke twice as wide, painted under the fill
          WebkitTextStroke: (clip ? p.outline : 4) ? `${outline * 2}px #000` : undefined, paintOrder: "stroke fill",
          textShadow: `${shadow}px ${shadow}px 0 rgba(0, 0, 0, ${p.shade})`,
        }}>
          {shown.map((i) => (
            <Fragment key={i}>
              <span className={i === at && clip ? `now${p.pop ? " pop" : ""}` : ""}
                style={i === at && clip ? { color: p.highlight } : undefined}>{words[i]}</span>{" "}
            </Fragment>
          ))}
        </div>
      </div>
      <div className="style-player">
        <button type="button" className="style-play" aria-label={playing ? "Pause the preview" : "Play the preview"}
          onClick={() => {
            if (!playing && t >= SECONDS) setT(0);
            setPlaying(!playing);
          }}><Icon name={playing ? "pause" : "play"} fill /></button>
        <span className="style-time" aria-hidden="true">{clock(t)} / {clock(SECONDS)}</span>
        <input type="range" min={0} max={SECONDS} step={0.05} value={t} aria-label="Preview time"
          aria-valuetext={`${t.toFixed(1)} of ${SECONDS} seconds`}
          onChange={(e) => { setPlaying(false); setT(Number(e.target.value)); }} />
      </div>
      <p className="style-hint">Sample words over a sample picture. {clip
        ? "Clips use this font, size, outline and colour, and light up each word as it is said."
        : "YouTube videos show white captions in this font."}</p>
    </section>
  );
}
