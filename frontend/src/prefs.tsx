import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { BY_ID } from "./office/cast";
import { studio } from "./studio";

/**
 * Appearance (theme, accent, density) saved to the account and applied to <html> at once: the change shows
 * immediately and is saved in the background; a failed save says so and offers Retry. Robot display names are
 * applied to the cast registry, so every label, tooltip and card uses them while every ID stays the same.
 */
export type Appearance = { theme: "system" | "light" | "dark"; accent: string; density: "comfortable" | "compact";
  motion: "system" | "full" | "reduced"; clips_mode: "highlights" | "full_stories"; remember_style: boolean };
const DEFAULT: Appearance = { theme: "system", accent: "violet", density: "comfortable", motion: "system",
  clips_mode: "highlights", remember_style: true };
const LOCAL = "clipforge.appearance";  // per-browser copy, so the first paint already has the right theme

type Ctx = { appearance: Appearance; set: (patch: Partial<Appearance>) => void; state: "saved" | "saving" | "failed";
  retry: () => void; namesVersion: number; refreshNames: () => Promise<void> };
const AppearanceContext = createContext<Ctx>({ appearance: DEFAULT, set: () => {}, state: "saved", retry: () => {},
  namesVersion: 0, refreshNames: async () => {} });
export const useAppearance = () => useContext(AppearanceContext);

const DEFAULT_NAMES: Record<string, string> = Object.fromEntries(Object.entries(BY_ID).map(([id, c]) => [id, c.name]));

export function deviceClass(): "desktop" | "tablet" | "phone" {
  const w = window.innerWidth;
  return w < 640 ? "phone" : w < 1024 ? "tablet" : "desktop";
}

function apply(a: Appearance) {
  const root = document.documentElement;
  const dark = a.theme === "dark" || (a.theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  root.dataset.theme = dark ? "dark" : "light";
  root.dataset.accent = a.accent;
  root.dataset.density = a.density;
  // Motion is not applied here: the per-browser Animations choice (motion.tsx) is its one owner, so a saved account
  // value can never override what this browser chose (accessibility needs differ between devices).
}

function readLocal(): Appearance {
  try {
    return { ...DEFAULT, ...JSON.parse(localStorage.getItem(LOCAL) || "{}") };
  } catch {
    return DEFAULT;
  }
}

/** Applies saved robot names to the cast registry; true when any shown name changed. */
export function applyRobotNames(names: Record<string, { display_name: string }>): boolean {
  let changed = false;
  for (const [id, c] of Object.entries(BY_ID)) {
    const next = names[id]?.display_name || DEFAULT_NAMES[id] || c.name;  // display only; c.id never changes
    if (next !== c.name) changed = true;
    c.name = next;
  }
  return changed;
}

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [appearance, setAppearance] = useState<Appearance>(readLocal);
  const [state, setState] = useState<"saved" | "saving" | "failed">("saved");
  const [namesVersion, setNamesVersion] = useState(0);
  const revision = useRef<number | undefined>(undefined);
  const pending = useRef<Partial<Appearance> | null>(null);

  useEffect(() => {
    apply(appearance);
    try {
      localStorage.setItem(LOCAL, JSON.stringify(appearance));
    } catch {
      /* the account copy is the record */
    }
  }, [appearance]);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const again = () => setAppearance((a) => ({ ...a }));
    mq.addEventListener("change", again);
    return () => mq.removeEventListener("change", again);
  }, []);

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
      setAppearance({ ...DEFAULT, ...(r.value as Partial<Appearance>) });
    }).catch(() => {});
    void refreshNames();
  }, [refreshNames]);

  const save = useCallback(async (patch: Partial<Appearance>) => {
    setState("saving");
    pending.current = patch;
    try {
      const r = await studio.saveAppearance(patch);  // a patch: other devices' fields are not overwritten
      revision.current = r.revision;
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

  return <AppearanceContext.Provider value={{ appearance, set, state, retry, namesVersion, refreshNames }}>{children}</AppearanceContext.Provider>;
}
