import { createContext, ReactNode, useCallback, useContext, useLayoutEffect, useMemo, useState } from "react";

const STORAGE_KEY = "clipfoundry.animationMode";
const LEGACY_KEY = "clipfoundry.reduceMotion";
const SYSTEM_QUERY = "(prefers-reduced-motion: reduce)";
const OFFICE_KEY = "clipforge.officeActivity";
export type AnimationMode = "system" | "full" | "reduced";
/** The office's decorative life: full; calm (no lounge break activities); low power (still robots, few redraws).
 * Real work and states are shown in every mode. */
export type OfficeActivity = "full" | "calm" | "low_power";

interface MotionState {
  /** Full is an explicit override; only Follow system consults the operating system. */
  reduceMotion: boolean;
  animationMode: AnimationMode;
  preferredReduceMotion: boolean;
  systemReducedMotion: boolean;
  pageHidden: boolean;
  persistent: boolean;
  setReduceMotion: (value: boolean) => void;
  setAnimationMode: (value: AnimationMode) => void;
  officeActivity: OfficeActivity;
  setOfficeActivity: (value: OfficeActivity) => void;
}

function storedActivity(): OfficeActivity {
  try {
    const v = window.localStorage.getItem(OFFICE_KEY);
    return v === "calm" || v === "low_power" ? v : "full";
  } catch {
    return "full";
  }
}

const MotionContext = createContext<MotionState | null>(null);

function preference() {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    const mode: AnimationMode = value === "full" || value === "reduced" || value === "system" ? value
      : window.localStorage.getItem(LEGACY_KEY) === "true" ? "reduced" : "system";
    return { mode, persistent: true };
  } catch {
    return { mode: "system" as AnimationMode, persistent: false };
  }
}

function systemPreference() {
  return typeof window.matchMedia === "function" && window.matchMedia(SYSTEM_QUERY).matches;
}

/** Browser-only visual preferences; these never become an application settings draft or touch processing. */
export function MotionProvider({ children }: { children: ReactNode }) {
  const [stored, setStored] = useState(preference);
  const [systemReducedMotion, setSystemReducedMotion] = useState(systemPreference);
  const [pageHidden, setPageHidden] = useState(() => document.hidden);
  const [officeActivity, setActivity] = useState<OfficeActivity>(storedActivity);
  const setOfficeActivity = useCallback((value: OfficeActivity) => {
    try {
      window.localStorage.setItem(OFFICE_KEY, value);
    } catch {
      /* lasts for this visit */
    }
    setActivity(value);
  }, []);
  const reduceMotion = stored.mode === "reduced" || (stored.mode === "system" && systemReducedMotion);

  const setAnimationMode = useCallback((mode: AnimationMode) => {
    let persistent = true;
    try {
      window.localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      persistent = false;
    }
    setStored({ mode, persistent });
  }, []);
  const setReduceMotion = useCallback((value: boolean) => setAnimationMode(value ? "reduced" : "system"),
    [setAnimationMode]);

  useLayoutEffect(() => {
    const media = typeof window.matchMedia === "function" ? window.matchMedia(SYSTEM_QUERY) : null;
    const changed = () => setSystemReducedMotion(media?.matches ?? false);
    changed();
    if (media?.addEventListener) media.addEventListener("change", changed);
    else media?.addListener(changed);
    return () => {
      if (media?.removeEventListener) media.removeEventListener("change", changed);
      else media?.removeListener(changed);
    };
  }, []);

  useLayoutEffect(() => {
    const visibility = () => setPageHidden(document.hidden);
    const storage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY || event.key === null) {
        setStored(preference());
      }
      if (event.key === OFFICE_KEY || event.key === null) setActivity(storedActivity());
    };
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("storage", storage);
    visibility();
    return () => {
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("storage", storage);
    };
  }, []);

  useLayoutEffect(() => {
    document.documentElement.dataset.motion = reduceMotion ? "reduced" : "full";
    document.documentElement.dataset.pageHidden = String(pageHidden);
  }, [reduceMotion, pageHidden]);

  const value = useMemo(() => ({ reduceMotion, animationMode: stored.mode,
    preferredReduceMotion: stored.mode === "reduced", systemReducedMotion,
    pageHidden, persistent: stored.persistent, setReduceMotion, setAnimationMode, officeActivity, setOfficeActivity }),
  [reduceMotion, stored, systemReducedMotion, pageHidden, setReduceMotion, setAnimationMode, officeActivity,
    setOfficeActivity]);
  return <MotionContext.Provider value={value}>{children}</MotionContext.Provider>;
}

export function useMotion(): MotionState {
  const value = useContext(MotionContext);
  if (!value) throw new Error("useMotion must be used inside MotionProvider");
  return value;
}
