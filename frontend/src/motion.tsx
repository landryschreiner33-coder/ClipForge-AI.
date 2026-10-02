import { createContext, ReactNode, useCallback, useContext, useLayoutEffect, useMemo, useState } from "react";

const STORAGE_KEY = "clipfoundry.reduceMotion";
const SYSTEM_QUERY = "(prefers-reduced-motion: reduce)";

interface MotionState {
  /** Effective reduction: the operating system and the app preference each keep animation still. */
  reduceMotion: boolean;
  preferredReduceMotion: boolean;
  systemReducedMotion: boolean;
  pageHidden: boolean;
  persistent: boolean;
  setReduceMotion: (value: boolean) => void;
}

const MotionContext = createContext<MotionState | null>(null);

function preference() {
  try {
    return { value: window.localStorage.getItem(STORAGE_KEY) === "true", persistent: true };
  } catch {
    return { value: false, persistent: false };
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
  const reduceMotion = stored.value || systemReducedMotion;

  const setReduceMotion = useCallback((value: boolean) => {
    let persistent = true;
    try {
      window.localStorage.setItem(STORAGE_KEY, String(value));
    } catch {
      persistent = false;
    }
    setStored({ value, persistent });
  }, []);

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
        setStored({ value: event.newValue === "true", persistent: true });
      }
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

  const value = useMemo(() => ({ reduceMotion, preferredReduceMotion: stored.value, systemReducedMotion,
    pageHidden, persistent: stored.persistent, setReduceMotion }),
  [reduceMotion, stored, systemReducedMotion, pageHidden, setReduceMotion]);
  return <MotionContext.Provider value={value}>{children}</MotionContext.Provider>;
}

export function useMotion(): MotionState {
  const value = useContext(MotionContext);
  if (!value) throw new Error("useMotion must be used inside MotionProvider");
  return value;
}
