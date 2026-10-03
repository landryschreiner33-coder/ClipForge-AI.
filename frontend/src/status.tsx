import { createContext, ReactNode, useContext, useEffect, useRef, useState } from "react";
import { ap, AutopilotStatus } from "./autopilot";

/**
 * Autopilot's status, read once for the whole app (the sidebar, Home and Autopilot share it). When ClipFoundry stops
 * answering, the last known status stays on screen, `lost` is set, and the shell says so: nothing shows as a
 * confirmed good state until it answers again.
 */
type StatusState = {
  st: AutopilotStatus | null;
  error: string;
  lost: boolean;
  lastOk: number | null;
  refresh: () => void;
  setData: (s: AutopilotStatus) => void;
};

const Ctx = createContext<StatusState>({ st: null, error: "", lost: false, lastOk: null, refresh: () => {}, setData: () => {} });
export const useStatus = () => useContext(Ctx);

const EVERY_MS = 3000;
const HIDDEN_MS = 15000;
/** Two missed answers in a row: not a hiccup any more. */
const LOST_AFTER = 2;

export function StatusProvider({ children }: { children: ReactNode }) {
  const [st, setSt] = useState<AutopilotStatus | null>(null);
  const [error, setError] = useState("");
  const [misses, setMisses] = useState(0);
  const [lastOk, setLastOk] = useState<number | null>(null);
  const [tick, setTick] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    let alive = true;
    const run = async () => {
      try {
        const v = await ap.status();
        if (!alive) return;
        setSt(v);
        setError("");
        setMisses(0);
        setLastOk(Date.now());
      } catch (e) {
        if (!alive) return;
        setError((e as Error).message);
        setMisses((m) => m + 1);
      }
      if (alive) timer.current = setTimeout(run, document.hidden ? HIDDEN_MS : EVERY_MS);
    };
    run();
    const wake = () => {
      if (!document.hidden) {
        clearTimeout(timer.current);
        run();
      }
    };
    document.addEventListener("visibilitychange", wake);
    return () => {
      alive = false;
      clearTimeout(timer.current);
      document.removeEventListener("visibilitychange", wake);
    };
  }, [tick]);
  const value: StatusState = {
    st, error, lost: misses >= LOST_AFTER, lastOk,
    refresh: () => setTick((x) => x + 1),
    setData: (s) => {
      setSt(s);
      setMisses(0);
      setLastOk(Date.now());
    },
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Autopilot's state in one word, for the sidebar, the top bar and page heads. */
export type ApState = { word: "On" | "Paused" | "Stopped" | "Off" | "Unknown"; tone: "good" | "warn" | "bad" | "neutral" };
export function autopilotState(st: AutopilotStatus | null, lost: boolean): ApState {
  if (!st || lost) return { word: "Unknown", tone: "neutral" };
  if (st.paused) return { word: "Stopped", tone: "bad" };
  if (st.enabled) return { word: "On", tone: "good" };
  if (!st.home.setup.started) return { word: "Off", tone: "neutral" };
  return { word: "Paused", tone: "warn" };
}
