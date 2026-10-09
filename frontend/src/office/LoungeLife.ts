/** Decorative break routines. This module never writes to, schedules or infers a durable job. */
import { CAST, Dir } from "./cast";
import { BREAK_SPOTS, BreakActivity, BreakSpot, Pt, REST_SEAT } from "./world";

interface Routine {
  spot: BreakSpot; destination: BreakSpot; held: Set<string>; eligible: boolean;
  elapsed: number; duration: number; visits: number; rotating: boolean;
}
export interface LoungeActor extends Pt { id: string; path: Pt[]; transfer: number | null }
const near = (a: Pt, b: Pt) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y) < 0.5;
const hash = (value: string) => {
  let out = 2166136261;
  for (let i = 0; i < value.length; i++) out = Math.imul(out ^ value.charCodeAt(i), 16777619);
  return out >>> 0;
};
const CYCLE: BreakActivity[] = ["arcade", "drink", "boardgame", "snack", "read", "rest"];
const PERIOD: Record<BreakActivity, number> = {
  arcade: 3.8, boardgame: 6.8, snack: 5.6, drink: 5.2, read: 7.8, rest: 6.4 };

/** Each destination is reserved before walking; the old place stays reserved until arrival. */
export class LoungeLife {
  private routines = new Map<string, Routine>();
  private claims = new Map<string, string>();
  private homes = new Map(CAST.map(c => [c.id, BREAK_SPOTS.find(s => near(s.at, REST_SEAT[c.id]))!]));

  constructor() { this.reset(); }

  /** Reduced/global Pause restore the stable home arrangement, with a deterministic still frame. */
  reset() {
    this.routines.clear(); this.claims.clear();
    for (const c of CAST) {
      const spot = this.homes.get(c.id)!;
      const duration = 15 + hash(c.id) % 11;
      this.routines.set(c.id, { spot, destination: spot, held: new Set([spot.id]), eligible: false,
        elapsed: duration * (0.18 + (hash(`${c.id}:start`) % 600) / 1000), duration, visits: 0, rotating: false });
      this.claims.set(spot.id, c.id);
    }
  }

  sync(id: string, lounge: boolean, eligible: boolean) {
    const routine = this.routines.get(id)!;
    if (!lounge) { this.release(id); routine.eligible = false; return; }
    if (!routine.held.size) {
      const home = this.homes.get(id)!;
      const spot = !this.claims.has(home.id) ? home : this.choose(id, routine, false);
      if (spot) this.reserve(id, routine, spot, false);
    }
    // A real individual pause stops the activity clock and future rounds. An existing walk finishes
    // at its reserved place; count it toward the two-walker limit until its origin is released.
    routine.eligible = eligible;
  }

  release(id: string) {
    const routine = this.routines.get(id)!;
    for (const slot of routine.held) if (this.claims.get(slot) === id) this.claims.delete(slot);
    routine.held.clear(); routine.rotating = false;
  }

  target(id: string): Pt { return this.routines.get(id)!.destination.at; }
  spot(id: string): BreakSpot | null {
    const routine = this.routines.get(id);
    return routine?.held.size ? routine.destination : null;
  }
  direction(id: string): Dir { return this.spot(id)?.dir || "down"; }
  activity(id: string): BreakActivity | null {
    const routine = this.routines.get(id);
    return routine?.eligible && routine.held.size ? routine.destination.activity : null;
  }
  phase(id: string): number {
    const routine = this.routines.get(id)!;
    return (routine.elapsed / PERIOD[routine.destination.activity]) % 1;
  }

  /** Only running visible Full frames advance this clock: no wall-clock catch-up after a freeze. */
  tick(dt: number, actors: Iterable<LoungeActor>) {
    const all = [...actors];
    for (const actor of all) {
      const routine = this.routines.get(actor.id)!;
      if (!routine.held.size || actor.transfer !== null || actor.path.length
        || !near(actor, routine.destination.at)) continue;
      if (routine.spot.id !== routine.destination.id) {
        for (const slot of routine.held)
          if (slot !== routine.destination.id && this.claims.get(slot) === actor.id) this.claims.delete(slot);
        routine.held = new Set([routine.destination.id]); routine.spot = routine.destination;
        routine.rotating = false; routine.elapsed = 0;
      }
      if (routine.eligible) routine.elapsed += Math.max(0, Math.min(dt, 0.1));
    }
    let walking = [...this.routines.values()].filter(r => r.rotating).length;
    // Oldest overdue break goes next: fixed cast order would let the first robots monopolize the spare places.
    const next = all.slice().sort((a, b) => {
      const one = this.routines.get(a.id)!, two = this.routines.get(b.id)!;
      return (two.elapsed - two.duration) - (one.elapsed - one.duration);
    });
    for (const actor of next) {
      if (walking >= 2) break;
      const routine = this.routines.get(actor.id)!;
      if (!routine.eligible || routine.rotating || actor.transfer !== null || actor.path.length
        || !near(actor, routine.destination.at) || routine.elapsed < routine.duration) continue;
      const destination = this.choose(actor.id, routine, true);
      if (!destination) continue;
      this.reserve(actor.id, routine, destination, true); walking++;
      routine.visits++; routine.duration = 16 + hash(`${actor.id}:${routine.visits}`) % 13;
    }
  }

  private reserve(id: string, routine: Routine, spot: BreakSpot, rotating: boolean) {
    this.claims.set(spot.id, id); routine.held.add(spot.id);
    routine.destination = spot; routine.rotating = rotating;
  }
  private choose(id: string, routine: Routine, change: boolean): BreakSpot | undefined {
    const desired = CYCLE[(hash(id) + routine.visits + 1) % CYCLE.length];
    return BREAK_SPOTS.filter(s => !this.claims.has(s.id)).sort((a, b) => {
      const score = (s: BreakSpot) => (s.activity === desired ? 0 : 1000)
        + (change && s.activity === routine.spot.activity ? 500 : 0) + hash(`${id}:${routine.visits}:${s.id}`) % 300;
      return score(a) - score(b);
    })[0];
  }
}
