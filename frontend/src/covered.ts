/**
 * A full-window editor (FilmCraft's, inside ClipForge) covers the page: the sky and the black holes behind it hold
 * still while it is open, so the editor has the computer to itself. Without a graphics card the moving sky alone
 * takes about a fifth of the page's time, and FilmCraft's editor runs on that same page.
 */
import { useEffect, useSyncExternalStore } from "react";

let covers = 0;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

/** While `on`, the page counts as covered. */
export function useCoverPage(on = true) {
  useEffect(() => {
    if (!on) return;
    covers += 1;
    notify();
    return () => {
      covers -= 1;
      notify();
    };
  }, [on]);
}

export function usePageCovered(): boolean {
  return useSyncExternalStore((l) => {
    listeners.add(l);
    return () => { listeners.delete(l); };
  }, () => covers > 0);
}
