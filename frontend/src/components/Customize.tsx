import { useEffect, useRef, useState } from "react";
import { errorText } from "../api";
import { AnimationMode, OfficeActivity, useMotion } from "../motion";
import { Appearance, DEFAULT_APPEARANCE, defaultLayout, deviceClass, Layout, Panel, useAppearance } from "../prefs";
import { Icon, Segmented, toast } from "./ui";

// shown as text and as swatches; the colours themselves live in theme.css (checked by tests/test_theme_contrast.py)
const PALETTES: { id: Appearance["palette"]; name: string; note: string; swatch: string[] }[] = [
  { id: "studio", name: "Studio", note: "Charcoal and navy", swatch: ["#0B0D14", "#151A25", "#1D2331"] },
  { id: "midnight", name: "Midnight", note: "Deep blue", swatch: ["#070B18", "#0F1730", "#172142"] },
  { id: "graphite", name: "Graphite", note: "Neutral grey", swatch: ["#0E0F11", "#18191C", "#212226"] },
  { id: "plum", name: "Plum", note: "Dark purple", swatch: ["#100B17", "#1A1325", "#231A31"] },
];
const ACCENTS: [string, string, string][] = [["violet", "Violet", "#9A7CFF"], ["teal", "Teal", "#2DD4BF"],
  ["blue", "Blue", "#4FA3FF"], ["coral", "Coral", "#FF8A5B"], ["green", "Green", "#3DD68C"], ["pink", "Pink", "#FF6FB5"]];
const PANEL_NAMES: Record<string, string> = { needs_you: "Needs you", pinned: "Pinned projects",
  current: "Current project", office: "Robot office", recent: "Recent projects", publishing: "Publishing",
  preview: "Preview", outputs: "Clips or sequence", transcript: "Look and sound", guidance: "Used from your Brain" };
const STUDIO_PRESETS: { name: string; order: string[]; hidden: string[] }[] = [
  { name: "Everything", order: ["needs_you", "pinned", "current", "office", "recent", "publishing"], hidden: [] },
  { name: "Focus on my work", order: ["needs_you", "pinned", "current", "recent", "office", "publishing"],
    hidden: ["office", "publishing"] },
  { name: "Office first", order: ["needs_you", "office", "current", "pinned", "recent", "publishing"], hidden: [] },
];

/** The one Customize studio entry (handoff section 3): every change shows at once behind the panel as a preview;
 * Save keeps it, Cancel (or Escape) puts everything back, Reset to defaults previews the defaults until you save. */
export default function Customize({ cloud }: { cloud: boolean }) {
  const { customizing } = useAppearance();
  return customizing ? <CustomizePanel cloud={cloud} /> : null;
}

function CustomizePanel({ cloud }: { cloud: boolean }) {
  const { saved, savedLayout, setDraft, setLayoutDraft, set, saveLayout, setCustomizing } = useAppearance();
  const motion = useMotion();
  const device = deviceClass();
  const [a, setA] = useState<Appearance>(saved);
  const [l, setL] = useState<Layout>(savedLayout);
  const [mode, setMode] = useState<AnimationMode>(motion.animationMode);
  const [office, setOffice] = useState<OfficeActivity>(motion.officeActivity);
  const before = useRef({ mode: motion.animationMode, office: motion.officeActivity });
  const opener = useRef<Element | null>(document.activeElement);
  const heading = useRef<HTMLHeadingElement>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  useEffect(() => {
    heading.current?.focus();
  }, []);
  useEffect(() => {
    setDraft(a);
  }, [a, setDraft]);
  useEffect(() => {
    setLayoutDraft(l);
  }, [l, setLayoutDraft]);
  useEffect(() => {
    motion.setAnimationMode(mode);
  }, [mode]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    motion.setOfficeActivity(office);
  }, [office]);  // eslint-disable-line react-hooks/exhaustive-deps

  const close = (keep: boolean) => {
    if (!keep) {
      motion.setAnimationMode(before.current.mode);
      motion.setOfficeActivity(before.current.office);
    }
    setDraft(null);
    setLayoutDraft(null);
    setCustomizing(false);
    (opener.current as HTMLElement | null)?.focus?.();
  };
  const save = async () => {
    setBusy(true);
    setProblem("");
    try {
      if (JSON.stringify(l) !== JSON.stringify(savedLayout)) await saveLayout(l);
      const patch = Object.fromEntries(Object.entries(a).filter(([k, v]) =>
        JSON.stringify(v) !== JSON.stringify(saved[k as keyof Appearance]))) as Partial<Appearance>;
      if (Object.keys(patch).length) set(patch);
      toast("Your studio is saved");
      close(true);
    } catch (e) {
      setProblem(errorText(e));
      setBusy(false);
    }
  };
  const reset = () => {
    setA({ ...DEFAULT_APPEARANCE, pinned: a.pinned, clips_mode: a.clips_mode, remember_style: a.remember_style });
    setL(defaultLayout(device));
    setMode("system");
    setOffice("full");
  };
  const patch = (p: Partial<Appearance>) => setA((x) => ({ ...x, ...p }));
  const screen = (id: string, fn: (ps: Panel[]) => Panel[]) =>
    setL((x) => ({ screens: { ...x.screens, [id]: fn([...(x.screens[id] || defaultLayout(device).screens[id])]) } }));
  const preset = (p: typeof STUDIO_PRESETS[number]) =>
    screen("studio", () => p.order.map((id) => ({ id, visible: !p.hidden.includes(id) })));

  return (
    <div className="customize" role="dialog" aria-modal="false" aria-labelledby="customize-title"
      onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); close(false); } }}>
      <div className="customize-head">
        <h2 id="customize-title" ref={heading} tabIndex={-1}>Customize studio</h2>
        <button type="button" className="btn btn-small btn-icon btn-quiet" aria-label="Cancel and close" onClick={() => close(false)}>
          <Icon name="x" /></button>
      </div>
      <div className="customize-body">
        <p className="small muted">Changes show right away behind this panel. Save keeps them; Cancel puts everything back.</p>

        <fieldset className="field"><legend>Colours</legend>
          <div className="palette-grid" role="radiogroup" aria-label="Palette">
            {PALETTES.map((p) => (
              <label key={p.id} className={`palette-choice${a.palette === p.id ? " on" : ""}`}>
                <input type="radio" name="customize-palette" value={p.id} checked={a.palette === p.id}
                  onChange={() => patch({ palette: p.id })} />
                <span className="swatches" aria-hidden="true">{p.swatch.map((c) => <i key={c} style={{ background: c }} />)}</span>
                <b>{p.name}</b><span className="tiny muted">{p.note}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className="field"><legend>Accent</legend>
          <div className="accent-row" role="radiogroup" aria-label="Accent">
            {ACCENTS.map(([id, name, hex]) => (
              <label key={id} className={`btn btn-small${a.accent === id ? " on" : ""}`}>
                <input type="radio" name="customize-accent" value={id} checked={a.accent === id}
                  onChange={() => patch({ accent: id })} />
                <span className="dot" aria-hidden="true" style={{ background: hex }} />{name}</label>
            ))}
          </div>
          <span className="tiny muted">Every accent is checked for readable text on every palette.</span>
        </fieldset>
        <div className="field"><span>Spacing</span>
          <Segmented label="Spacing" value={a.density} onChange={(v) => patch({ density: v })}
            options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]} /></div>
        <div className="field"><span>Text size</span>
          <Segmented label="Text size" value={a.text_size} onChange={(v) => patch({ text_size: v })}
            options={[{ value: "standard", label: "Standard" }, { value: "large", label: "Large" }, { value: "larger", label: "Larger" }]} /></div>

        <fieldset className="field"><legend>Studio page on this {device}</legend>
          <div className="row wrap">
            {STUDIO_PRESETS.map((p) => <button key={p.name} type="button" className="btn btn-small" onClick={() => preset(p)}>{p.name}</button>)}
          </div>
          <PanelList panels={l.screens.studio || []} onChange={(fn) => screen("studio", fn)} sized={false} />
          <div className="field"><span>Office on the Studio page</span>
            <Segmented label="Office on the Studio page" value={a.office_size} onChange={(v) => patch({ office_size: v })}
              options={[{ value: "expanded", label: "Expanded" }, { value: "compact", label: "Compact" }]} />
            <span className="tiny muted">Compact is shorter and shows details only when you pick a robot or room.</span></div>
          <span className="tiny muted">Pin a project with Pin on its card (Studio or Projects); pinned ones show here first.
            {a.pinned.length ? ` ${a.pinned.length} pinned.` : ""}</span>
        </fieldset>
        <fieldset className="field"><legend>Editor panels on this {device}</legend>
          <PanelList panels={l.screens.review || []} onChange={(fn) => screen("review", fn)} sized={device !== "phone"} />
        </fieldset>

        <fieldset className="field"><legend>Motion (this browser)</legend>
          <Segmented label="Motion" value={mode} onChange={setMode}
            options={[{ value: "system", label: "Follow system" }, { value: "full", label: "Full" }, { value: "reduced", label: "Reduced" }]} />
          <span>Office animation</span>
          <Segmented label="Office animation" value={office} onChange={setOffice}
            options={[{ value: "full", label: "Full" }, { value: "calm", label: "Calm" }, { value: "low_power", label: "Low power" }]} />
          <span className="tiny muted">Calm stops the lounge activities; Low power keeps robots still and redraws once a second.
            Real work and states always show.</span>
        </fieldset>
        <div className="field"><span>Robot names</span>
          <a className="btn btn-small" href="#/office/team"><Icon name="user" />Rename robots on the Team page</a></div>

        <p className="tiny muted">Colours, spacing, text size, panels and pinned projects are saved {cloud
          ? "to your account for this workspace" : "in ClipForge on this computer"}; panels are kept separately for
          desktop, tablet and phone. Motion and office animation are saved in this browser only.</p>
        {problem && <p className="error-text" role="alert"><Icon name="alert" />{problem}</p>}
      </div>
      <div className="customize-foot">
        <button type="button" className="btn btn-small btn-quiet" onClick={reset}><Icon name="refresh" />Reset to defaults</button>
        <span className="spacer" />
        <button type="button" className="btn btn-small" onClick={() => close(false)}>Cancel</button>
        <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => void save()}>Save</button>
      </div>
    </div>
  );
}

/** Panels of one screen: show or hide each (one always stays), move up or down with buttons, widths where they apply. */
function PanelList({ panels, onChange, sized }: { panels: Panel[]; onChange: (fn: (ps: Panel[]) => Panel[]) => void;
  sized: boolean }) {
  const shown = panels.filter((p) => p.visible).length;
  const move = (i: number, by: number) => onChange((ps) => {
    const [x] = ps.splice(i, 1);
    ps.splice(i + by, 0, x);
    return ps;
  });
  return (
    <ol className="seq panel-list">
      {panels.map((p, i) => (
        <li key={p.id} className={p.visible ? "" : "off"}>
          <label><input type="checkbox" checked={p.visible} disabled={p.visible && shown === 1}
            onChange={() => onChange((ps) => ps.map((x) => (x.id === p.id ? { ...x, visible: !x.visible } : x)))} />
            {" "}{PANEL_NAMES[p.id] || p.id}</label>
          <span className="spacer" />
          <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${PANEL_NAMES[p.id]} up`} disabled={i === 0}
            onClick={() => move(i, -1)}><Icon name="chev" className="point-up" /></button>
          <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${PANEL_NAMES[p.id]} down`}
            disabled={i === panels.length - 1} onClick={() => move(i, 1)}><Icon name="chev" className="point-down" /></button>
          {sized && p.size !== undefined && (
            <label className="small panel-width">Width <input type="range" min={10} max={90} value={Math.round(p.size * 100)}
              aria-label={`${PANEL_NAMES[p.id]} width`}
              onChange={(e) => onChange((ps) => ps.map((x) => (x.id === p.id ? { ...x, size: Number(e.target.value) / 100 } : x)))} /></label>
          )}
        </li>
      ))}
    </ol>
  );
}
