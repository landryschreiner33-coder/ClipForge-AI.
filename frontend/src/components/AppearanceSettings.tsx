import { useCallback, useEffect, useState } from "react";
import { errorText } from "../api";
import { useMotion } from "../motion";
import { deviceClass, useAppearance } from "../prefs";
import { studio } from "../studio";
import { Icon, Segmented, toast } from "./ui";

const ACCENTS = [["violet", "#9A7CFF"], ["blue", "#4FA3FF"], ["coral", "#FF8A5B"], ["green", "#3DD68C"], ["pink", "#FF6FB5"]];
const SCREEN_NAMES: Record<string, string> = { create: "Create", review: "Review", office: "Office" };
const PANEL_NAMES: Record<string, string> = { intake: "File", style: "Style", destinations: "Accounts", summary: "Summary",
  preview: "Preview", outputs: "Clips or sequence", transcript: "Look and sound", guidance: "Used from your Brain",
  map: "Office map", team: "Team", activity: "Activity" };
type Panel = { id: string; visible: boolean; size?: number };
type Layout = { screens: Record<string, Panel[]> };

/** The layout saved for this device class (desktop, tablet or phone), ordered and filtered for one screen. */
export function useLayout(screen: string): { panels: Panel[]; visible: (id: string) => boolean } {
  const [layout, setLayout] = useState<Layout | null>(null);
  useEffect(() => {
    studio.layout(deviceClass()).then((r) => setLayout(r.value)).catch(() => setLayout(null));
  }, []);
  const panels = layout?.screens[screen] || [];
  return { panels, visible: (id) => !layout || panels.find((p) => p.id === id)?.visible !== false };
}

export default function AppearanceSettings() {
  const { appearance, set, state, retry } = useAppearance();
  const motion = useMotion();
  const device = deviceClass();
  const [layout, setLayout] = useState<Layout | null>(null);
  const [revision, setRevision] = useState(0);
  const load = useCallback(() => studio.layout(device).then((r) => { setLayout(r.value); setRevision(r.revision); }), [device]);
  useEffect(() => {
    void load();
  }, [load]);
  const saveLayout = async (next: Layout) => {
    setLayout(next);
    try {
      await studio.saveLayout(device, next, revision);
      await load();
    } catch (e) {
      toast(errorText(e), true);
      await load();
    }
  };
  const change = (screen: string, fn: (p: Panel[]) => Panel[]) => layout && void saveLayout({ screens: { ...layout.screens, [screen]: fn([...layout.screens[screen]]) } });

  return (
    <div className="stack-5">
      <section className="panel" aria-labelledby="ap-look">
        <div className="panel-head"><h2 id="ap-look">Appearance</h2>
          <span className={`save-state ${state === "failed" ? "bad" : ""}`} aria-live="polite">
            {state === "saving" ? "Saving…" : state === "failed" ? <>Not saved. <button type="button" className="link-btn" onClick={retry}>Retry</button></> : "Saved to your account"}</span></div>
        <div className="grid-2">
          <div className="field"><span>Theme</span>
            <Segmented label="Theme" value={appearance.theme} onChange={(v) => set({ theme: v as typeof appearance.theme })}
              options={[{ value: "system", label: "Follow system" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} /></div>
          <div className="field"><span>Spacing</span>
            <Segmented label="Spacing" value={appearance.density} onChange={(v) => set({ density: v as typeof appearance.density })}
              options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]} /></div>
          <div className="field"><span>Motion</span>
            <Segmented label="Motion" value={motion.animationMode} onChange={(v) => motion.setAnimationMode(v)}
              options={[{ value: "system", label: "Follow system" }, { value: "full", label: "Full" }, { value: "reduced", label: "Reduced" }]} />
            <span className="small muted">Saved for this browser only, like Animations in Defaults.</span></div>
          <fieldset className="field"><legend>Accent colour</legend>
            <div className="row-actions" style={{ justifyContent: "flex-start" }}>
              {ACCENTS.map(([id, hex]) => (
                <button key={id} type="button" className={`btn btn-small ${appearance.accent === id ? "btn-primary" : ""}`}
                  aria-pressed={appearance.accent === id} onClick={() => set({ accent: id })}>
                  <span aria-hidden="true" style={{ width: 14, height: 14, borderRadius: 7, background: hex, display: "inline-block" }} />
                  {id[0].toUpperCase() + id.slice(1)}</button>
              ))}
            </div></fieldset>
        </div>
      </section>
      <section className="panel" aria-labelledby="ap-layout">
        <div className="panel-head"><h2 id="ap-layout">Layout on this {device}</h2>
          <button type="button" className="btn btn-small" onClick={async () => { await studio.resetLayout(device); await load(); toast("Layout reset; your edits, styles and robot names are unchanged"); }}>
            <Icon name="refresh" />Reset layout</button></div>
        <p className="small muted">Each device keeps its own layout, so a phone never gets desktop panel sizes. At least one panel stays visible.</p>
        {layout && Object.entries(layout.screens).map(([screen, panels]) => (
          <fieldset key={screen} className="stack-3"><legend className="label">{SCREEN_NAMES[screen] || screen}</legend>
            <ol className="seq">{panels.map((p, i) => (
              <li key={p.id} className={p.visible ? "" : "off"}>
                <span className="idx">{i + 1}</span>
                <label><input type="checkbox" checked={p.visible} disabled={p.visible && panels.filter((x) => x.visible).length === 1}
                  onChange={() => change(screen, (ps) => ps.map((x) => (x.id === p.id ? { ...x, visible: !x.visible } : x)))} /> {PANEL_NAMES[p.id] || p.id}</label>
                <div className="row-actions">
                  <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${PANEL_NAMES[p.id]} up`} disabled={i === 0}
                    onClick={() => change(screen, (ps) => { const [x] = ps.splice(i, 1); ps.splice(i - 1, 0, x); return ps; })}><Icon name="chev" className="rot-up" /></button>
                  <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${PANEL_NAMES[p.id]} down`} disabled={i === panels.length - 1}
                    onClick={() => change(screen, (ps) => { const [x] = ps.splice(i, 1); ps.splice(i + 1, 0, x); return ps; })}><Icon name="chev" /></button>
                  {p.size !== undefined && <label className="small">Width <input type="range" min={10} max={90} value={Math.round(p.size * 100)}
                    aria-label={`${PANEL_NAMES[p.id]} width`}
                    onChange={(e) => change(screen, (ps) => ps.map((x) => (x.id === p.id ? { ...x, size: Number(e.target.value) / 100 } : x)))} /></label>}
                </div>
              </li>))}</ol>
          </fieldset>
        ))}
      </section>
    </div>
  );
}

/** Panels of one screen in the saved order, hidden ones left out, desktop/tablet widths applied (phones stack). */
export function LayoutFlow({ screen, sections }: { screen: string; sections: Record<string, React.ReactNode> }) {
  const { panels } = useLayout(screen);
  const order = panels.length ? panels : Object.keys(sections).map((id) => ({ id, visible: true } as Panel));
  return (
    <div className="layout-flow">
      {order.filter((p) => p.visible && sections[p.id]).map((p) => (
        <div key={p.id} className="layout-cell" style={p.size ? { flexBasis: `calc(${(p.size * 100).toFixed(1)}% - var(--s5))` } : undefined}>
          {sections[p.id]}
        </div>
      ))}
    </div>
  );
}
