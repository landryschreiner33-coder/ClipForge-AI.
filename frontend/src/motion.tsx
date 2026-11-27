import { createContext, ReactNode, useCallback, useContext, useLayoutEffect, useMemo, useState } from "react";

const STORAGE_KEY = "clipfoundry.animationMode";
const LEGACY_KEY = "clipfoundry.reduceMotion";
const SYSTEM_QUERY = "(prefers-reduced-motion: reduce)";
const OFFICE_KEY = "clipforge.officeActivity";
const LOOK_KEY = "clipforge.spaceLook";
const SOUND_KEY = "clipforge.sounds";
const TASER_KEY = "clipforge.taser";
const LOOKS = ["orbit", "lighter"] as const;
const lookNow = () => storedChoice<SpaceLook>(LOOK_KEY, LOOKS, "orbit");
const soundsNow = () => storedChoice(SOUND_KEY, ["on", "off"] as const, "off") === "on";
const taserNow = () => storedChoice(TASER_KEY, ["show", "hide"] as const, "show") === "show";
export type AnimationMode = "system" | "full" | "reduced";
/** The office's decorative life: full; calm (no lounge break activities); low power (still robots, few redraws).
 * Real work and states are shown in every mode. */
export type OfficeActivity = "full" | "calm" | "low_power";
/** The big black hole: seen from the orbiting ship (every pixel's light traced), or the lighter turning disk. */
export type SpaceLook = "orbit" | "lighter";

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
  spaceLook: SpaceLook;
  setSpaceLook: (value: SpaceLook) => void;
  /** Little sound effects (the office's Taser): off unless turned on in Settings → Appearance. */
  sounds: boolean;
  setSounds: (value: boolean) => void;
  /** The robot office's Taser button (an easter egg): shown unless hidden in Settings → Appearance. */
  taser: boolean;
  setTaser: (value: boolean) => void;
}

function storedChoice<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = window.localStorage.getItem(key);
    return (allowed as readonly string[]).includes(v ?? "") ? (v as T) : fallback;
  } catch {
    return fallback;
  }
}

function keep(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* lasts for this visit */
  }
}

function storedActivity(): OfficeActivity {
  try {
    const v = window.localStorage.getItem(OFFICE_KEY);
    return v === "calm" || v === "low_power" ? v : "full";
  } catch {
    return "full";
  }
}

/** Full or Reduced, set the same way by the Studio's Reduce motion switch and Settings → Appearance → Motion, so the two
 * always agree: Full follows the system when the system allows motion, and overrides it when the system asks for less. */
export function motionChoice(full: boolean, systemReducedMotion: boolean): AnimationMode {
  return full ? (systemReducedMotion ? "full" : "system") : "reduced";
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
  const [spaceLook, setLook] = useState<SpaceLook>(lookNow);
  const [sounds, setSound] = useState(soundsNow);
  const [taser, setTaserShown] = useState(taserNow);
  const setTaser = useCallback((value: boolean) => {
    keep(TASER_KEY, value ? "show" : "hide");
    setTaserShown(value);
  }, []);
  const setSpaceLook = useCallback((value: SpaceLook) => {
    keep(LOOK_KEY, value);
    setLook(value);
  }, []);
  const setSounds = useCallback((value: boolean) => {
    keep(SOUND_KEY, value ? "on" : "off");
    setSound(value);
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
      if (event.key === LOOK_KEY || event.key === null) setLook(lookNow());
      if (event.key === SOUND_KEY || event.key === null) setSound(soundsNow());
      if (event.key === TASER_KEY || event.key === null) setTaserShown(taserNow());
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
    pageHidden, persistent: stored.persistent, setReduceMotion, setAnimationMode, officeActivity, setOfficeActivity,
    spaceLook, setSpaceLook, sounds, setSounds, taser, setTaser }),
  [reduceMotion, stored, systemReducedMotion, pageHidden, setReduceMotion, setAnimationMode, officeActivity,
    setOfficeActivity, spaceLook, setSpaceLook, sounds, setSounds, taser, setTaser]);
  return <MotionContext.Provider value={value}>{children}</MotionContext.Provider>;
}

export function useMotion(): MotionState {
  const value = useContext(MotionContext);
  if (!value) throw new Error("useMotion must be used inside MotionProvider");
  return value;
}
