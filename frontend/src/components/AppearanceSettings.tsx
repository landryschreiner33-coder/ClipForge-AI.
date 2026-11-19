import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { motionChoice, OfficeActivity, useMotion } from "../motion";
import { Appearance, deviceClass, Panel, useAppearance } from "../prefs";
import { PREVIEW_MESSAGE } from "../preview";
import { ACCENTS, PALETTES } from "./Customize";
import { Icon, IconName, Segmented } from "./ui";
import "./AppearanceSettings.css";

/** The panels saved for this device class (desktop, tablet or phone) for one screen, as Customize studio previews
 * or saved them. */
export function useLayout(screen: string): { panels: Panel[]; visible: (id: string) => boolean } {
  const { layout } = useAppearance();
  const panels = layout.screens[screen] || [];
  return { panels, visible: (id) => panels.find((p) => p.id === id)?.visible !== false };
}

/**
 * Settings → Appearance (the space studio, 2026-11-19): each choice applies and saves at once, beside a live preview of
 * the Studio on a desktop, tablet or phone. Motion is the same switch as Reduce motion under the ship (motionChoice).
 * Customize studio keeps the panel layouts, which are saved for each kind of device.
 */
export default function AppearanceSettings() {
  const { appearance, set, state, retry, setCustomizing } = useAppearance();
  const motion = useMotion();
  const accent = ACCENTS.find(([id]) => id === appearance.accent);
  return (
    <div className="ap-space">
      <section className="ap-form" aria-labelledby="ap-look">
        <div className="ap-head">
          <h2 id="ap-look">Appearance</h2>
          <span className={`ap-saved ${state}`} aria-live="polite">
            {state === "saving" ? "Saving…" : state === "failed"
              ? <>Not saved. <button type="button" className="link-btn" onClick={retry}>Try again</button></>
              : <><Icon name="check" />Saved</>}
          </span>
        </div>
        <div className="ap-row">
          <span className="ap-label" id="ap-accent">Accent color</span>
          <div className="ap-control ap-accents">
            <div className="ap-swatches" role="radiogroup" aria-labelledby="ap-accent">
              {ACCENTS.map(([id, name, hex]) => (
                <label key={id} className={`ap-swatch${appearance.accent === id ? " on" : ""}`} title={name}>
                  <input type="radio" name="ap-accent" value={id} aria-label={name} checked={appearance.accent === id}
                    onChange={() => set({ accent: id })} />
                  <i style={{ background: hex }} aria-hidden="true" />
                </label>
              ))}
            </div>
            <span className="ap-accent-name" aria-hidden="true">{accent ? accent[1] : appearance.accent}</span>
          </div>
        </div>
        <Choice id="ap-palette" label="Background" value={appearance.palette}
          onChange={(v) => set({ palette: v as Appearance["palette"] })}
          options={PALETTES.map((p) => [p.id, `${p.name}: ${p.note.toLowerCase()}`])} />
        <Choice id="ap-density" label="Spacing" value={appearance.density}
          onChange={(v) => set({ density: v as Appearance["density"] })}
          options={[["comfortable", "Comfortable"], ["compact", "Compact"]]} />
        <Choice id="ap-text" label="Text size" value={appearance.text_size}
          onChange={(v) => set({ text_size: v as Appearance["text_size"] })}
          options={[["standard", "Standard"], ["large", "Large"], ["larger", "Larger"]]} />
        <Choice id="ap-ship" label="Ship view" value={appearance.office_size}
          onChange={(v) => set({ office_size: v as Appearance["office_size"] })}
          options={[["expanded", "Expanded"], ["compact", "Compact"]]}
          hint="Compact is shorter and opens a robot's or room's details when you pick one." />
        <div className="ap-row">
          <span className="ap-label" id="ap-motion">Motion</span>
          <div className="ap-control">
            <Segmented labelledBy="ap-motion" value={motion.reduceMotion ? "reduced" : "full"}
              onChange={(v) => motion.setAnimationMode(motionChoice(v === "full", motion.systemReducedMotion))}
              options={[{ value: "full", label: "Full" }, { value: "reduced", label: "Reduced" }]} />
            <p className="ap-hint">The same switch as Reduce motion under the ship, saved in this browser.
              {motion.systemReducedMotion && motion.reduceMotion ? " Your computer asks for less motion." : ""}</p>
          </div>
        </div>
        <Choice id="ap-life" label="Robot activity" value={motion.officeActivity}
          onChange={(v) => motion.setOfficeActivity(v as OfficeActivity)}
          options={[["full", "Full"], ["calm", "Calm"], ["low_power", "Low power"]]}
          hint="Real work always shows. Calm stops the robots' breaks, games and snacks; Low power keeps them still and
            redraws the ship once a second." />
        <div className="ap-foot">
          <button type="button" className="btn btn-outline" onClick={() => setCustomizing(true)}>
            <Icon name="layers" />Customize studio</button>
          <span className="ap-foot-note">Layouts are saved by device (this is a {deviceClass()}).</span>
        </div>
      </section>
      <StudioPreview />
    </div>
  );
}

/** One labelled choice: a list that applies as soon as it changes. */
function Choice({ id, label, value, options, onChange, hint }: {
  id: string; label: string; value: string; options: [string, string][]; onChange: (v: string) => void; hint?: ReactNode;
}) {
  return (
    <div className="ap-row">
      <label className="ap-label" htmlFor={id}>{label}</label>
      <div className="ap-control">
        <select id={id} value={value} onChange={(e) => onChange(e.target.value)}
          aria-describedby={hint ? `${id}-hint` : undefined}>
          {options.map(([v, words]) => <option key={v} value={v}>{words}</option>)}
        </select>
        {hint && <p className="ap-hint" id={`${id}-hint`}>{hint}</p>}
      </div>
    </div>
  );
}

type Device = "desktop" | "tablet" | "phone";
const DEVICES: Record<Device, { w: number; h: number; label: string; icon: IconName }> = {
  desktop: { w: 1440, h: 900, label: "Desktop", icon: "screen" },
  tablet: { w: 820, h: 1180, label: "Tablet", icon: "tablet" },
  phone: { w: 390, h: 844, label: "Phone", icon: "phone" },
};

/**
 * The Studio itself in a frame at a desktop, tablet or phone size, scaled to fit. It reads the same projects, robots
 * and work as the Studio page and shows this page's appearance (or Customize's draft); it is inert, so it cannot be
 * clicked or tabbed into, and it never saves anything (preview.ts).
 */
function StudioPreview() {
  const { appearance } = useAppearance();
  const [device, setDevice] = useState<Device>(() => deviceClass());
  const box = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLIFrameElement | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setWidth(el.clientWidth);
    measure();
    const watch = new ResizeObserver(measure);
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  const send = useCallback(() => {
    frame.current?.contentWindow?.postMessage({ type: PREVIEW_MESSAGE, appearance }, window.location.origin);
  }, [appearance]);
  useEffect(send, [send]);
  useEffect(() => {
    const ready = (e: MessageEvent) => {
      if (e.source === frame.current?.contentWindow && e.data?.type === `${PREVIEW_MESSAGE}:ready`) send();
    };
    window.addEventListener("message", ready);
    return () => window.removeEventListener("message", ready);
  }, [send]);
  const frameRef = useCallback((el: HTMLIFrameElement | null) => {
    frame.current = el;
    el?.setAttribute("inert", "");  // React 18 has no inert prop; set as the frame appears
  }, []);
  const d = DEVICES[device];
  const scale = width ? Math.min(width / d.w, 560 / d.h) : 0;
  return (
    <section className="ap-preview" aria-labelledby="ap-preview-h">
      <h2 id="ap-preview-h">Studio preview</h2>
      <p className="sr-only">A live picture of your Studio with these choices, at the size you pick below. It cannot be
        clicked.</p>
      <div className="ap-preview-box" ref={box} style={{ height: Math.round(d.h * scale) || undefined }}>
        <div className={`ap-device ${device}`} style={{ width: Math.round(d.w * scale), height: Math.round(d.h * scale) }}>
          {scale > 0 && (
            <iframe key={device} ref={frameRef} title="Studio preview" src="/?preview=studio#/" width={d.w} height={d.h}
              tabIndex={-1} aria-hidden="true" style={{ transform: `scale(${scale})` }} />
          )}
        </div>
      </div>
      <div className="ap-devices" role="radiogroup" aria-label="Preview size">
        {(Object.keys(DEVICES) as Device[]).map((k) => (
          <label key={k} className={device === k ? "on" : ""}>
            <input type="radio" name="ap-device" value={k} checked={device === k} onChange={() => setDevice(k)} />
            <Icon name={DEVICES[k].icon} />{DEVICES[k].label}
          </label>
        ))}
      </div>
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
