import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { BY_ID, CORE } from "./office/cast";
import { IN_PREVIEW, PREVIEW_MESSAGE } from "./preview";
import { studio } from "./studio";

/**
 * Appearance (palette, accent, density, text size, the Studio's office size and pinned projects) and the panel layout
 * for this device, saved to the account and applied to <html>. ClipForge is dark only. Customize studio previews a
 * draft live (setDraft / setLayoutDraft) and saves it, or drops it on Cancel. Robot display names are applied to the
 * cast registry, so every label, tooltip and card uses them while every ID stays the same.
 */
export type Appearance = { palette: "studio" | "midnight" | "graphite" | "plum"; accent: string;
  density: "comfortable" | "compact"; text_size: "standard" | "large" | "larger"; motion: "system" | "full" | "reduced";
  office_size: "compact" | "expanded"; pinned: string[]; clips_mode: "highlights" | "full_stories" | "story_parts";
  remember_style: boolean;
  /** Make a YouTube video: ClipForge AI asks questions when something is unclear, or just does it. */
  video_setup_mode: "ask" | "auto";
  /** The colour picked for the Custom accent (accent "custom"). */
  accent_color: string;
  /** Worked out by the server from accent_color: the shades that keep text readable on every palette. */
  accent_shades?: AccentShades };
export type AccentShades = { primary: string; primary_hover: string; primary_tint: string; adjusted: boolean };
export const DEFAULT_APPEARANCE: Appearance = { palette: "studio", accent: "blue", density: "comfortable",
  text_size: "standard", motion: "system", office_size: "expanded", pinned: [], clips_mode: "highlights",
  remember_style: true, video_setup_mode: "ask", accent_color: "#6CCFF6" };
const DEFAULT = DEFAULT_APPEARANCE;
const LOCAL = "clipforge.appearance";  // per-browser copy, so the first paint already has the right palette

export type Panel = { id: string; visible: boolean; size?: number };
export type Layout = { screens: Record<string, Panel[]> };
// the same panels as clipfoundry/studio/prefs.py PANELS; only the editor's sit side by side and have widths
export const PANELS: Record<string, string[]> = {
  studio: ["needs_you", "pinned", "current", "office", "recent", "publishing"],
  review: ["preview", "outputs", "transcript", "guidance"],
};
// the editor's default widths (clipfoundry/studio/prefs.py REVIEW_SIZE): the player and the transcript take the wider column
const REVIEW_SIZE: Record<string, number> = { preview: 0.6, outputs: 0.4, transcript: 0.6, guidance: 0.4 };
export function defaultLayout(device = deviceClass()): Layout {
  return { screens: Object.fromEntries(Object.entries(PANELS).map(([screen, ids]) => [screen, ids.map((id) => ({
    id, visible: true,
    ...(screen === "review" && device !== "phone" ? { size: REVIEW_SIZE[id] ?? Math.round(1000 / ids.length) / 1000 } : {}),
  }))])) };
}

type Ctx = { appearance: Appearance; set: (patch: Partial<Appearance>) => void; state: "saved" | "saving" | "failed";
  retry: () => void; namesVersion: number; refreshNames: () => Promise<void>;
  /** the saved appearance, before any preview */
  saved: Appearance; setDraft: (a: Appearance | null) => void;
  layout: Layout; savedLayout: Layout; layoutRevision: number; setLayoutDraft: (l: Layout | null) => void;
  saveLayout: (l: Layout) => Promise<void>; resetLayout: () => Promise<void>;
  customizing: boolean; setCustomizing: (open: boolean) => void;
  /** a deleted project leaves this page's pinned list (the server already took it off the saved one) */
  forgetPin: (id: string) => void };
const AppearanceContext = createContext<Ctx>({ appearance: DEFAULT, set: () => {}, state: "saved", retry: () => {},
  namesVersion: 0, refreshNames: async () => {}, saved: DEFAULT, setDraft: () => {}, layout: { screens: {} },
  savedLayout: { screens: {} }, layoutRevision: 0, setLayoutDraft: () => {}, saveLayout: async () => {},
  resetLayout: async () => {}, customizing: false, setCustomizing: () => {}, forgetPin: () => {} });
export const useAppearance = () => useContext(AppearanceContext);

const DEFAULT_NAMES: Record<string, string> = { ...Object.fromEntries(Object.entries(BY_ID).map(([id, c]) => [id, c.name])),
  [CORE.id]: CORE.name };

export function deviceClass(): "desktop" | "tablet" | "phone" {
  const w = window.innerWidth;
  return w < 640 ? "phone" : w < 1024 ? "tablet" : "desktop";
}

function apply(a: Appearance) {
  const root = document.documentElement;
  delete root.dataset.theme;  // there is one (dark) theme
  root.dataset.palette = a.palette;
  root.dataset.accent = a.accent;
  // the Custom accent: its readable shades (worked out by the server), or the preset's colours from theme.css
  const custom = a.accent === "custom" ? a.accent_shades : undefined;
  for (const [token, value] of [["--primary", custom?.primary], ["--primary-hover", custom?.primary_hover],
    ["--primary-tint", custom?.primary_tint]] as const) {
    if (value) root.style.setProperty(token, value);
    else root.style.removeProperty(token);
  }
  root.dataset.density = a.density;
  root.dataset.text = a.text_size;
  // Motion is not applied here: the per-browser Animations choice (motion.tsx) is its one owner, so a saved account
  // value can never override what this browser chose (accessibility needs differ between devices).
}

function clean(v: Partial<Appearance> & { theme?: unknown }): Appearance {
  const out = { ...DEFAULT };
  for (const k of Object.keys(DEFAULT) as (keyof Appearance)[]) if (v[k] !== undefined) (out as Record<string, unknown>)[k] = v[k];
  if (v.accent_shades) out.accent_shades = v.accent_shades;
  return out;  // a saved Light or System theme from before is simply not read: ClipForge is dark only
}

function readLocal(): Appearance {
  try {
    return clean(JSON.parse(localStorage.getItem(LOCAL) || "{}"));
  } catch {
    return DEFAULT;
  }
}

/** Applies saved robot names to the cast registry; true when any shown name changed. */
export function applyRobotNames(names: Record<string, { display_name: string }>): boolean {
  let changed = false;
  for (const [id, c] of [...Object.entries(BY_ID), [CORE.id, CORE] as const]) {
    const next = names[id]?.display_name || DEFAULT_NAMES[id] || c.name;  // display only; c.id never changes
    if (next !== c.name) changed = true;
    c.name = next;
  }
  return changed;
}

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [appearance, setAppearance] = useState<Appearance>(readLocal);
  const [draft, setDraft] = useState<Appearance | null>(null);
  const [state, setState] = useState<"saved" | "saving" | "failed">("saved");
  const [namesVersion, setNamesVersion] = useState(0);
  const [savedLayout, setSavedLayout] = useState<Layout>(() => defaultLayout());
  const [layoutRevision, setLayoutRevision] = useState(0);
  const [layoutDraft, setLayoutDraft] = useState<Layout | null>(null);
  const [customizing, setCustomizing] = useState(false);
  const revision = useRef<number | undefined>(undefined);
  const pending = useRef<Partial<Appearance> | null>(null);
  const shown = draft || appearance;

  useEffect(() => {
    apply(shown);
  }, [shown]);

  useEffect(() => {
    if (IN_PREVIEW) return;
    try {
      localStorage.setItem(LOCAL, JSON.stringify(appearance));  // the saved choice only, never a preview
    } catch {
      /* the account copy is the record */
    }
  }, [appearance]);

  // Settings → Appearance's Studio preview: show what that page sends (its saved choice or Customize's draft)
  useEffect(() => {
    if (!IN_PREVIEW) return;
    const take = (e: MessageEvent) => {
      if (e.source !== window.parent || e.origin !== window.location.origin) return;
      const m = e.data as { type?: string; appearance?: Partial<Appearance> } | null;
      if (m?.type === PREVIEW_MESSAGE && m.appearance) setDraft(clean(m.appearance));
    };
    window.addEventListener("message", take);
    window.parent.postMessage({ type: `${PREVIEW_MESSAGE}:ready` }, window.location.origin);
    return () => window.removeEventListener("message", take);
  }, []);

  const loadLayout = useCallback(async () => {
    try {
      const r = await studio.layout(deviceClass());
      setSavedLayout(r.value);
      setLayoutRevision(r.revision);
    } catch {
      /* the preset stays */
    }
  }, []);
  useEffect(() => {
    void loadLayout();
  }, [loadLayout]);
  const saveLayout = useCallback(async (l: Layout) => {
    await studio.saveLayout(deviceClass(), l, layoutRevision);
    await loadLayout();
  }, [layoutRevision, loadLayout]);
  const resetLayout = useCallback(async () => {
    await studio.resetLayout(deviceClass());
    await loadLayout();
  }, [loadLayout]);

  const refreshNames = useCallback(async () => {
    try {
      // Redraw the page only when a name really changed: a redraw starts the page over, and on every start it
      // would throw away what was just picked (a chosen file, a typed word).
      if (applyRobotNames(await studio.robotNames())) setNamesVersion((n) => n + 1);
    } catch {
      /* the default names stay */
    }
  }, []);

  useEffect(() => {
    studio.appearance().then((r) => {
      revision.current = r.revision;
      setAppearance(clean(r.value as Partial<Appearance>));
    }).catch(() => {});
    void refreshNames();
  }, [refreshNames]);

  const save = useCallback(async (patch: Partial<Appearance>) => {
    if (IN_PREVIEW) return;  // the preview never saves
    setState("saving");
    pending.current = patch;
    try {
      const r = await studio.saveAppearance(patch);  // a patch: other devices' fields are not overwritten
      revision.current = r.revision;
      // the Custom accent's readable shades come back from the server, for the colour that was saved
      const back = r.value as Partial<Appearance>;
      if (back.accent_shades) {
        setAppearance((a) => (a.accent_color === back.accent_color ? { ...a, accent_shades: back.accent_shades } : a));
      }
      pending.current = null;
      setState("saved");
    } catch {
      setState("failed");
    }
  }, []);

  const set = useCallback((patch: Partial<Appearance>) => {
    setAppearance((a) => ({ ...a, ...patch }));
    void save(patch);
  }, [save]);

  const retry = useCallback(() => {
    if (pending.current) void save(pending.current);
  }, [save]);

  const forgetPin = useCallback((id: string) => {
    // only this page's copy: saving a list from here could undo a pin made on another device meanwhile
    setAppearance((a) => (a.pinned.includes(id) ? { ...a, pinned: a.pinned.filter((x) => x !== id) } : a));
    const waiting = pending.current;  // a save that failed and may be retried must not pin it again
    if (waiting?.pinned?.includes(id)) pending.current = { ...waiting, pinned: waiting.pinned.filter((x) => x !== id) };
  }, []);

  const value = useMemo(() => ({ appearance: shown, set, state, retry, namesVersion, refreshNames, saved: appearance,
    setDraft, layout: layoutDraft || savedLayout, savedLayout, layoutRevision, setLayoutDraft, saveLayout, resetLayout,
    customizing, setCustomizing, forgetPin }), [shown, set, state, retry, namesVersion, refreshNames, appearance,
    layoutDraft, savedLayout, layoutRevision, saveLayout, resetLayout, customizing, forgetPin]);
  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>;
}
