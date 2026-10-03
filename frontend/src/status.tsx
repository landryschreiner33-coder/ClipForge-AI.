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
  const revision = useRef(0);
  const refreshPoll = useRef(() => {});
  useEffect(() => {
    let alive = true;
    let reading = false;
    let again = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      clearTimeout(timer);
      if (reading) {
        // Returning to the tab or refreshing must not start a second polling loop.
        again = true;
        return;
      }
      reading = true;
      const before = revision.current;
      try {
        const v = await ap.status();
        if (!alive || before !== revision.current) return;
        setSt(v);
        setError("");
        setMisses(0);
        setLastOk(Date.now());
      } catch (e) {
        if (!alive || before !== revision.current) return;
        setError((e as Error).message);
        setMisses((m) => m + 1);
      } finally {
        reading = false;
        if (alive) {
          if (again) {
            again = false;
            run();
          } else {
            timer = setTimeout(run, document.hidden ? HIDDEN_MS : EVERY_MS);
          }
        }
      }
    };
    refreshPoll.current = () => {
      revision.current += 1;
      run();
    };
    run();
    const wake = () => {
      if (!document.hidden) run();
    };
    document.addEventListener("visibilitychange", wake);
    return () => {
      alive = false;
      clearTimeout(timer);
      refreshPoll.current = () => {};
      document.removeEventListener("visibilitychange", wake);
    };
  }, []);
  const value: StatusState = {
    st, error, lost: misses >= LOST_AFTER, lastOk,
    refresh: () => refreshPoll.current(),
    setData: (s) => {
      // An answer to an earlier GET cannot undo a successful Start/Pause action.
      revision.current += 1;
      setSt(s);
      setError("");
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
