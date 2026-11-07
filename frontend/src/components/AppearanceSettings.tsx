import { useMotion } from "../motion";
import { deviceClass, Panel, useAppearance } from "../prefs";
import { Icon } from "./ui";

const PALETTE_NAMES: Record<string, string> = { studio: "Studio", midnight: "Midnight", graphite: "Graphite", plum: "Plum" };
const OFFICE_WORDS: Record<string, string> = { full: "Full", calm: "Calm", low_power: "Low power" };
const MOTION_WORDS: Record<string, string> = { system: "Follow system", full: "Full", reduced: "Reduced" };
const cap = (s: string) => s[0].toUpperCase() + s.slice(1).replace("_", " ");

/** The panels saved for this device class (desktop, tablet or phone) for one screen, as Customize studio previews
 * or saved them. */
export function useLayout(screen: string): { panels: Panel[]; visible: (id: string) => boolean } {
  const { layout } = useAppearance();
  const panels = layout.screens[screen] || [];
  return { panels, visible: (id) => panels.find((p) => p.id === id)?.visible !== false };
}

/** Settings → Appearance: what is chosen now, and the one place to change it (Customize studio). */
export default function AppearanceSettings() {
  const { appearance, state, retry, setCustomizing } = useAppearance();
  const motion = useMotion();
  return (
    <section className="panel" aria-labelledby="ap-look">
      <div className="panel-head"><h2 id="ap-look">Appearance</h2>
        <span className={`save-state ${state === "failed" ? "bad" : ""}`} aria-live="polite">
          {state === "saving" ? "Saving…" : state === "failed" ? <>Not saved. <button type="button" className="link-btn" onClick={retry}>Retry</button></> : "Saved"}</span></div>
      <p className="small">ClipForge has one dark design. Choose its colours, spacing, text size, the Studio page's panels
        and motion in Customize studio, with a live preview.</p>
      <dl className="facts small">
        <div><dt>Colours</dt><dd>{PALETTE_NAMES[appearance.palette]} with {cap(appearance.accent)}</dd></div>
        <div><dt>Spacing and text</dt><dd>{cap(appearance.density)}, {cap(appearance.text_size)} text</dd></div>
        <div><dt>Office on the Studio page</dt><dd>{cap(appearance.office_size)}</dd></div>
        <div><dt>Motion (this browser)</dt><dd>{MOTION_WORDS[motion.animationMode]}; office animation {OFFICE_WORDS[motion.officeActivity]}</dd></div>
        <div><dt>Layouts</dt><dd>Kept separately for desktop, tablet and phone (this is a {deviceClass()})</dd></div>
      </dl>
      <button type="button" className="btn btn-primary" onClick={() => setCustomizing(true)}><Icon name="sliders" />Customize studio</button>
    </section>
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
