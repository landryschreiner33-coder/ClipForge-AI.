import { useCallback, useEffect, useRef, useState } from "react";
import { office, OfficeEvent, Snapshot } from "./api";

/**
 * The office feed on the page: one authoritative snapshot, then the events after its cursor (bounded polling).
 *
 * - Duplicates are dropped by event id, and nothing at or below the cursor is applied twice.
 * - A `reset` answer (the cursor is older than the kept history, or from another database) reloads the snapshot
 *   instead of replaying.
 * - A long backlog (the page was asleep, the connection was lost) is not replayed as live work: the snapshot is
 *   reloaded and only events from the last LIVE_SECONDS are handed to the animation.
 * - After two missed answers the page says the connection is lost and keeps the last known state, marked stale.
 *
 * Events only change what is drawn. Nothing here creates, approves or finishes work.
 */
const EVERY_MS = 1500;
const HIDDEN_MS = 8000;
const SNAPSHOT_MS = 10000;   // the snapshot is re-read this often even without events (role states, health)
const LOST_AFTER = 2;
export const LIVE_SECONDS = 30;  // older events are history: listed, never walked
const KEEP = 200;
const BACKLOG = 150;         // more new events than this at once: reload instead of replaying
const HISTORY = 40;          // events listed from before the page opened

export type Listener = (events: OfficeEvent[], serverTime: number) => void;

export interface OfficeFeed {
  snap: Snapshot | null;
  events: OfficeEvent[];
  error: string;
  lost: boolean;
  lastOk: number | null;
  /** server time minus this browser's clock (s), to tell live events from history */
  skew: number;
  reload: () => Promise<void>;
  setSnap: (s: Snapshot) => void;
  subscribe: (fn: Listener) => () => void;
}

export function useOffice(): OfficeFeed {
  const [snap, setSnapState] = useState<Snapshot | null>(null);
  const [events, setEvents] = useState<OfficeEvent[]>([]);
  const [error, setError] = useState("");
  const [misses, setMisses] = useState(0);
  const [lastOk, setLastOk] = useState<number | null>(null);
  const [skew, setSkew] = useState(0);
  const cursor = useRef(0);
  const seen = useRef(new Set<number>());
  const listeners = useRef(new Set<Listener>());
  const lastSnapshot = useRef(0);
  const wanted = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const alive = useRef(true);
  const missed = useRef(0);

  const ok = (serverTime: number) => {
    if (missed.current >= LOST_AFTER) wanted.current = true;  // reconnected: reconcile with a fresh snapshot
    missed.current = 0;
    setMisses(0);
    setError("");
    setLastOk(Date.now());
    setSkew(serverTime - Date.now() / 1000);
  };

  const setSnap = useCallback((s: Snapshot) => {
    // A snapshot older than what was already applied must not move the cursor back.
    if (s.cursor >= cursor.current) cursor.current = s.cursor;
    lastSnapshot.current = Date.now();
    setSnapState(s);
  }, []);

  const reload = useCallback(async () => {
    const s = await office.snapshot();
    if (!alive.current) return;
    setSnap(s);
    ok(s.server_time);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setSnap]);

  useEffect(() => {
    alive.current = true;
    const tick = async () => {
      try {
        if (!lastSnapshot.current || wanted.current || Date.now() - lastSnapshot.current > SNAPSHOT_MS) {
          const first = !lastSnapshot.current;
          wanted.current = false;
          await reload();
          if (first && cursor.current > 0) {
            // the last few events as history, so Activity is not empty on arrival (only the last LIVE_SECONDS move)
            const recent = await office.events(Math.max(0, cursor.current - HISTORY), HISTORY);
            if (!alive.current) return;
            fresh(recent.events, recent.server_time, false);
          }
        }
        const page = await office.events(cursor.current);
        if (!alive.current) return;
        ok(page.server_time);
        if (page.reset || page.events.length > BACKLOG || (page.more && page.latest - cursor.current > BACKLOG)) {
          // Too far behind: the current state is what matters, not a replay of everything missed.
          await reload();
          const recent = await office.events(Math.max(0, cursor.current - 20), 20);
          fresh(recent.events.filter((e) => recent.server_time - e.at < LIVE_SECONDS), recent.server_time, false);
        } else {
          fresh(page.events, page.server_time, true);
          if (page.more) {
            clearTimeout(timer.current);
            timer.current = setTimeout(tick, 50);
            return;
          }
        }
      } catch (e) {
        if (!alive.current) return;
        missed.current += 1;
        setMisses(missed.current);
        setError((e as Error).message);
      }
      if (alive.current) timer.current = setTimeout(tick, document.hidden ? HIDDEN_MS : EVERY_MS);
    };
    const fresh = (rows: OfficeEvent[], serverTime: number, advance: boolean) => {
      const out: OfficeEvent[] = [];
      for (const e of rows) {
        if (seen.current.has(e.id)) continue;
        seen.current.add(e.id);
        out.push(e);
        if (advance && e.id > cursor.current) cursor.current = e.id;
      }
      if (seen.current.size > 4000) seen.current = new Set([...seen.current].slice(-2000));
      if (!out.length) return;
      out.sort((a, b) => a.id - b.id);
      setEvents((prev) => [...prev, ...out].sort((a, b) => a.id - b.id).slice(-KEEP));
      // A finished step changes role states: read the snapshot again soon rather than wait for the timer.
      if (out.some((e) => e.type !== "brain_lookup")) lastSnapshot.current = Math.min(lastSnapshot.current, Date.now() - SNAPSHOT_MS + 400);
      for (const fn of listeners.current) fn(out, serverTime);
    };
    tick();
    const wake = () => {
      if (!document.hidden) {
        clearTimeout(timer.current);
        wanted.current = true;
        tick();
      }
    };
    document.addEventListener("visibilitychange", wake);
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
      document.removeEventListener("visibilitychange", wake);
    };
  }, [reload]);

  const subscribe = useCallback((fn: Listener) => {
    listeners.current.add(fn);
    return () => {
      listeners.current.delete(fn);
    };
  }, []);

  return { snap, events, error, lost: misses >= LOST_AFTER, lastOk, skew, reload, setSnap, subscribe };
}
