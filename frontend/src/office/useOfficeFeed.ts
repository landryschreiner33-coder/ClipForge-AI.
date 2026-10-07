import { useCallback, useEffect, useRef, useState } from "react";
import { OfficeEvent, OfficeSnapshot, office } from "./officeApi";

/**
 * The Office's live data: the authoritative snapshot plus the event feed after its cursor.
 *
 * Bounded polling: events every 2.5 s while the tab is visible and every 15 s while it is hidden; the snapshot is read
 * again when new events arrive, every few ticks (measured progress changes without events), after a `gap` and after
 * a reconnect. Events are kept by id (duplicates dropped, ordered by id). Two failed requests in a row mark the data
 * as stale; nothing on screen may then read as current.
 */
const VISIBLE_MS = 2500;
const HIDDEN_MS = 15000;
const SNAPSHOT_EVERY = 2; // ticks without events between snapshot reads
const KEEP = 200;
const LOST_AFTER = 2;

export type FeedState = {
  snap: OfficeSnapshot | null;
  events: OfficeEvent[];
  lost: boolean;
  lastOk: number | null;
  error: string;
  reload: () => void;
  /** Called with events that arrived live (not on first load, gap or reconnect): only these may animate. */
  setLiveListener: (fn: ((e: OfficeEvent[]) => void) | null) => void;
};

export function mergeEvents(list: OfficeEvent[], more: OfficeEvent[]): OfficeEvent[] {
  if (!more.length) return list;
  const byId = new Map<number, OfficeEvent>();
  for (const e of list) byId.set(e.id, e);
  for (const e of more) byId.set(e.id, e);
  return [...byId.values()].sort((a, b) => a.id - b.id).slice(-KEEP);
}

export function useOfficeFeed(): FeedState {
  const [snap, setSnap] = useState<OfficeSnapshot | null>(null);
  const [events, setEvents] = useState<OfficeEvent[]>([]);
  const [misses, setMisses] = useState(0);
  const [lastOk, setLastOk] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const listener = useRef<((e: OfficeEvent[]) => void) | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cursor = -1; // unknown until the first snapshot
    let quiet = 0;
    let failures = 0;
    let busy = false; // a visibility wake-up must not start a second request while one is in flight
    const ok = () => {
      if (!alive) return;
      failures = 0;
      setMisses(0);
      setError("");
      setLastOk(Date.now());
    };
    const loadSnapshot = async () => {
      const s = await office.snapshot();
      if (!alive) return;
      // Never move the cursor backwards: an older snapshot would replay events already shown.
      cursor = Math.max(cursor, s.cursor);
      setSnap(s);
      setEvents((list) => mergeEvents(list, s.recent || []));
    };
    const run = async () => {
      if (busy) return;
      busy = true;
      try {
        const wasLost = failures >= LOST_AFTER;
        if (cursor < 0 || wasLost) {
          await loadSnapshot();
        } else {
          const page = await office.events(cursor);
          if (!alive) return;
          if (page.gap) {
            // More happened than one page holds: reload the current state instead of replaying a stale backlog.
            await loadSnapshot();
          } else {
            const fresh = page.events.filter((e) => e.id > cursor);
            cursor = Math.max(cursor, page.cursor);
            if (fresh.length) {
              setEvents((list) => mergeEvents(list, fresh));
              listener.current?.(fresh);
              quiet = 0;
              await loadSnapshot();
            } else if (++quiet >= SNAPSHOT_EVERY) {
              quiet = 0;
              await loadSnapshot();
            }
          }
        }
        ok();
      } catch (e) {
        if (!alive) return;
        failures += 1;
        setMisses(failures);
        setError((e as Error).message);
      }
      busy = false;
      if (alive) timer = setTimeout(run, document.hidden ? HIDDEN_MS : VISIBLE_MS);
    };
    run();
    const wake = () => {
      if (!document.hidden) {
        clearTimeout(timer);
        run();
      }
    };
    document.addEventListener("visibilitychange", wake);
    return () => {
      alive = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", wake);
    };
  }, [tick]);

  const setLiveListener = useCallback((fn: ((e: OfficeEvent[]) => void) | null) => {
    listener.current = fn;
  }, []);
  return {
    snap, events, lost: misses >= LOST_AFTER, lastOk, error, reload: () => setTick((t) => t + 1), setLiveListener,
  };
}
