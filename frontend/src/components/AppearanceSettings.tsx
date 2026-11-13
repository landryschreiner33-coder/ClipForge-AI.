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

type Column = { x: number; width: number; cells: Panel[] };

/**
 * Packs sized panels into columns. A panel goes under the earlier panel that starts at the same place with the same
 * width, so a short panel beside a tall one is not followed by a hole: in the editor the player sits above the look
 * settings while the long sequence runs down the other column. A panel whose width does not match any column of the
 * current band starts a new band (its own row of columns). Panels without a width (phones) all stack in one column.
 */
export function packColumns(cells: Panel[]): Column[][] {
  const near = (a: number, b: number) => Math.abs(a - b) < 0.02;
  const bands: Column[][] = [];
  let band: Column[] = [];
  let cursor = 0;
  let extent = 0;
  for (const p of cells) {
    const w = p.size && p.size > 0 && p.size < 1 ? p.size : 1;
    if (cursor + w > 1.02) cursor = 0;
    let col = band.find((c) => near(c.x, cursor) && near(c.width, w));
    if (!col) {
      if (cursor < extent - 0.02) {  // it would overlap a column of this band: start a new band
        bands.push(band);
        band = []; cursor = 0; extent = 0;
      }
      col = { x: cursor, width: w, cells: [] };
      band.push(col);
      extent = cursor + w;
    }
    col.cells.push(p);
    cursor = col.x + col.width;
  }
  if (band.length) bands.push(band);
  return bands;
}

/** Panels of one screen in the saved order, hidden ones left out, desktop/tablet widths applied (phones stack). */
export function LayoutFlow({ screen, sections }: { screen: string; sections: Record<string, React.ReactNode> }) {
  const { panels } = useLayout(screen);
  const order = panels.length ? panels : Object.keys(sections).map((id) => ({ id, visible: true } as Panel));
  const bands = packColumns(order.filter((p) => p.visible && sections[p.id]));
  return (
    <div className="layout-bands">
      {bands.map((band, i) => (
        <div key={i} className="layout-flow">
          {band.map((col) => (
            <div key={col.cells[0].id} className="layout-col"
              style={col.width < 1 ? { flexBasis: `calc(${(col.width * 100).toFixed(1)}% - var(--s5))` } : undefined}>
              {col.cells.map((p) => <div key={p.id} className="layout-cell">{sections[p.id]}</div>)}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
