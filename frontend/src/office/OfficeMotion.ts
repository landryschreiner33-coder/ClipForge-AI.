/** Visual choreography only. Durable jobs are never delayed or changed by a walk or a document transfer. */
import { BY_ID, CAST, Dir } from "./cast";
import { OfficeEvent, RoleRow, Snapshot } from "./api";
import { BreakActivity, Pt, REST_SEAT, roomOf, route, STATION } from "./world";
import { LoungeLife } from "./LoungeLife";
import type { Pose } from "./sprites";
import type { RobotPosture } from "./StudioArt";

export interface WorkCard {
  job_id: string; kind: string; ref_type: string; ref_id: string; state: string; summary: string;
  from?: string; to?: string;
}
export interface MotionActor {
  id: string; x: number; y: number; dir: Dir; path: Pt[]; card: WorkCard | null;
  transfer: number | null; reaction: { pose: Pose; until: number } | null;
}
export interface DocumentPass { id: number; from: Pt; to: Pt; progress: number }
interface Transfer {
  id: number; from: string; to: string; card: WorkCard; phase: "approach" | "pass" | "received";
  started: number; until: number;
}
interface Owner { role: string; job: string; kind: string; ref: string; at: number; cursor: number }
const SPEED = 130;
const ACTIVE = new Set(["working", "reviewing", "error"]);
const POSE: Record<string, Pose> = {
  idle: "idle", working: "work", waiting: "wait", retrying: "retry", error: "error", reviewing: "review",
  paused: "paused", unavailable: "unavailable",
};
const CROSS_JOB: Record<string, string[]> = {
  hunt_source: ["analyze_source"], package_clip: ["quality_check"], regenerate_clip: ["package_clip"],
};
const same = (a: Pt, b: Pt) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y) < 0.5;
const facing = (a: Pt, b: Pt): Dir => Math.abs(b.x - a.x) > Math.abs(b.y - a.y)
  ? b.x > a.x ? "right" : "left" : b.y > a.y ? "down" : "up";

export function placements(rows: RoleRow[]): Record<string, { at: Pt; lounge: boolean }> {
  const states = new Map(rows.map(r => [r.id, r.state]));
  return Object.fromEntries(CAST.map(c => {
    const lounge = !ACTIVE.has(states.get(c.id) || "unavailable");
    return [c.id, { at: lounge ? REST_SEAT[c.id] : STATION[c.id], lounge }];
  }));
}

export class OfficeMotion {
  readonly actors = new Map<string, MotionActor>();
  private rows = new Map<string, RoleRow>();
  private targets: ReturnType<typeof placements> = {};
  private transfers = new Map<number, Transfer>();
  private jobOwners = new Map<string, Owner>();
  private refOwners = new Map<string, Owner>();
  private cutoff: number;
  private lounge = new LoungeLife();
  private stopped = false;

  constructor(snap: Snapshot) {
    this.cutoff = snap.cursor;
    this.reconcile(snap, true);
  }

  reconcile(snap: Snapshot, reduced: boolean) {
    this.cutoff = Math.max(this.cutoff, snap.cursor);
    this.stopped = snap.run.state === "stopped";
    this.rows = new Map(snap.roles.map(r => [r.id, r]));
    this.targets = placements(snap.roles);
    if (reduced) this.lounge.reset();
    // Release every real worker's place first, before assigning any returning off-duty worker.
    for (const c of CAST) if (!this.targets[c.id].lounge) this.lounge.release(c.id);
    for (const c of CAST) this.lounge.sync(c.id, this.targets[c.id].lounge, this.canBreak(c.id));
    for (const c of CAST) {
      const target = this.destination(c.id);
      let actor = this.actors.get(c.id);
      if (!actor) {
        actor = { id: c.id, ...target, dir: "down", path: [], card: null, transfer: null, reaction: null };
        this.actors.set(c.id, actor);
      }
      if (actor.transfer !== null && this.blocked(actor.id)) this.cancel(actor.transfer);
      if (this.blocked(actor.id)) actor.reaction = null;
      if (actor.transfer !== null) continue;
      this.go(actor, target, reduced);
      this.faceBreak(actor);
    }
    this.seedOwners(snap);
    this.trim(this.jobOwners); this.trim(this.refOwners);
  }

  /** Connection recovery uses the latest state, with no replay of transfers missed while offline. */
  resync(snap: Snapshot) {
    this.clearTransfers();
    this.cutoff = snap.cursor;
    this.jobOwners.clear(); this.refOwners.clear();
    this.reconcile(snap, true);
  }

  react(id: string, pose: Pose, now: number) {
    const a = this.actors.get(id);
    if (a && !this.blocked(id)) a.reaction = { pose, until: now + 2200 };
  }

  events(events: OfficeEvent[], serverTime: number, now: number, reduced: boolean) {
    for (const event of events) {
      if (event.id <= this.cutoff || serverTime - event.at > 30 || event.at > serverTime + 5) continue;
      if (event.type === "report" && BY_ID[event.data?.worker] && BY_ID[event.role]) {
        this.transfer(event.data.worker, event.role, event, now, reduced);
      }
      if (!event.job_id || !BY_ID[event.role] || event.data?.routine) continue;
      if (event.type !== "job_started" && event.type !== "job_stage") continue;
      const previous = this.jobOwners.get(event.job_id);
      const ref = `${event.ref_type}:${event.ref_id}`;
      if (previous && (event.id <= previous.cursor || event.at < previous.at)) continue;
      if (previous && (previous.kind !== event.kind || previous.ref !== ref)) continue;
      if (event.type === "job_stage" && previous && previous.role !== event.role) {
        this.transfer(previous.role, event.role, event, now, reduced);
      } else if (event.type === "job_started" && event.ref_type && event.ref_id) {
        const before = this.refOwners.get(`${event.ref_type}:${event.ref_id}`);
        if (before && before.job !== event.job_id && before.cursor < event.id && event.at - before.at <= 30 && event.at >= before.at
          && CROSS_JOB[before.kind]?.includes(event.kind)) {
          this.transfer(before.role, event.role, event, now, reduced);
        }
      }
      const owner = { role: event.role, job: event.job_id, kind: event.kind, ref, at: event.at, cursor: event.id };
      this.jobOwners.set(event.job_id, owner);
      if (event.ref_type && event.ref_id) this.refOwners.set(`${event.ref_type}:${event.ref_id}`, owner);
    }
    this.trim(this.jobOwners); this.trim(this.refOwners);
  }

  tick(dt: number, now: number, reduced: boolean, frozen: boolean) {
    if (frozen) return;
    if (!reduced) this.lounge.tick(dt, this.actors.values());
    for (const a of this.actors.values()) {
      if (a.reaction && a.reaction.until < now) a.reaction = null;
      // Individually paused/unavailable workers may finish returning to a reserved resting place,
      // but only eligible workers rotate through decorative activities once they arrive.
      if (a.transfer === null) this.go(a, this.destination(a.id), reduced);
      this.walk(a, dt, reduced);
      this.faceBreak(a);
    }
    for (const tr of [...this.transfers.values()]) {
      const from = this.actors.get(tr.from)!, to = this.actors.get(tr.to)!;
      if (this.blocked(tr.from) || this.blocked(tr.to) || now - tr.started > 18000) {
        this.cancel(tr.id); continue;
      }
      if (reduced) { this.cancel(tr.id); continue; }
      if (tr.phase === "approach" && !from.path.length && !to.path.length) {
        tr.phase = "pass"; tr.until = now + 700;
        from.dir = facing(from, to); to.dir = facing(to, from);
      } else if (tr.phase === "pass" && now >= tr.until) {
        tr.phase = "received"; tr.until = now + 1000;
        from.card = null; to.card = tr.card;
      } else if (tr.phase === "received" && now >= tr.until) {
        this.cancel(tr.id);
      }
    }
    // Every completed transfer returns to the latest actual destination, without waiting for another poll.
    for (const a of this.actors.values()) if (a.transfer === null) {
      this.go(a, this.destination(a.id), reduced); this.faceBreak(a);
    }
  }

  pose(a: MotionActor): Pose {
    const state = this.rows.get(a.id)?.state || "unavailable";
    const transfer = a.transfer === null ? null : this.transfers.get(a.transfer);
    if (a.path.length) return a.card ? "carry" : "walk";
    if (this.blocked(a.id)) return POSE[state];
    if (transfer) {
      if (transfer.phase === "approach") return a.id === transfer.from ? "carry" : "wait";
      if (transfer.phase === "pass") return "review";
      return a.id === transfer.to ? "carry" : "idle";
    }
    return a.reaction?.pose || POSE[state];
  }

  posture(a: MotionActor): RobotPosture {
    if (a.path.length || a.transfer !== null || a.reaction) return "stand";
    if (this.targets[a.id]?.lounge && same(a, this.destination(a.id))) {
      return this.breakActivity(a) ? this.lounge.spot(a.id)?.posture || "rest" : "rest";
    }
    if (["working", "reviewing"].includes(this.rows.get(a.id)?.state || "") && same(a, STATION[a.id])) return "desk";
    return "stand";
  }

  /** Break metadata is decorative; pose/state badges still retain the authoritative job state. */
  breakActivity(a: MotionActor): BreakActivity | null {
    return a.path.length || a.transfer !== null || a.reaction || !this.targets[a.id]?.lounge
      || !same(a, this.destination(a.id)) ? null : this.lounge.activity(a.id);
  }
  breakPhase(a: MotionActor): number { return this.lounge.phase(a.id); }
  breakSpot(a: MotionActor): string | null {
    return a.transfer !== null || !this.targets[a.id]?.lounge ? null : this.lounge.spot(a.id)?.id || null;
  }

  passes(now: number): DocumentPass[] {
    return [...this.transfers.values()].filter(tr => tr.phase === "pass").map(tr => ({
      id: tr.id, from: this.actors.get(tr.from)!, to: this.actors.get(tr.to)!, progress: Math.min(1, Math.max(0, 1 - (tr.until - now) / 700)),
    }));
  }

  activeTransfer(): { from: string; to: string; phase: Transfer["phase"]; card: WorkCard } | null {
    const all = [...this.transfers.values()], tr = all[all.length - 1];
    return tr ? { from: tr.from, to: tr.to, phase: tr.phase, card: tr.card } : null;
  }
  isSender(a: MotionActor): boolean {
    return a.transfer !== null && this.transfers.get(a.transfer)?.from === a.id;
  }

  clearTransfers() { for (const id of [...this.transfers.keys()]) this.cancel(id); }

  private transfer(from: string, to: string, event: OfficeEvent, now: number, reduced: boolean) {
    const sender = this.actors.get(from), receiver = this.actors.get(to);
    if (!sender || !receiver || from === to || this.blocked(from) || this.blocked(to)) return;
    if (reduced) { this.react(to, "review", now); return; }
    if (sender.transfer !== null) this.cancel(sender.transfer);
    if (receiver.transfer !== null) this.cancel(receiver.transfer);
    this.lounge.release(from); this.lounge.release(to);
    const card: WorkCard = { job_id: event.job_id, kind: event.kind, ref_type: event.ref_type,
      ref_id: event.ref_id, state: event.data?.state || "stage", summary: event.message, from, to };
    const station = STATION[to], room = roomOf(station)!;
    const side = station.x - room.x > room.w / 2 ? -1 : 1;
    const meet = { x: station.x, y: station.y + 9 };
    const offer = { x: station.x + side * 34, y: station.y + 9 };
    this.go(sender, offer, false); this.go(receiver, meet, false);
    sender.card = card; receiver.card = null;
    sender.transfer = event.id; receiver.transfer = event.id;
    sender.reaction = null; receiver.reaction = null;
    this.transfers.set(event.id, { id: event.id, from, to, card, phase: "approach", started: now, until: 0 });
  }

  private cancel(id: number) {
    const tr = this.transfers.get(id);
    if (!tr) return;
    for (const who of [tr.from, tr.to]) {
      const a = this.actors.get(who)!;
      if (a.transfer !== id) continue;
      a.transfer = null; a.card = null; a.path = [];
      this.lounge.sync(who, this.targets[who]?.lounge || false, this.canBreak(who));
    }
    this.transfers.delete(id);
  }

  private blocked(id: string) { return ["paused", "unavailable"].includes(this.rows.get(id)?.state || "unavailable"); }
  private canBreak(id: string) {
    const state = this.rows.get(id)?.state;
    return state === "idle" || state === "waiting" || state === "retrying" || (state === "paused" && this.stopped);
  }
  private destination(id: string): Pt {
    return this.targets[id]?.lounge ? this.lounge.target(id) : this.targets[id].at;
  }
  private faceBreak(a: MotionActor) {
    if (!a.path.length && a.transfer === null && this.targets[a.id]?.lounge && same(a, this.destination(a.id))) {
      a.dir = this.lounge.direction(a.id);
    }
  }
  private go(a: MotionActor, target: Pt, reduced: boolean) {
    if (reduced) { a.x = target.x; a.y = target.y; a.path = []; a.dir = "down"; return; }
    const end = a.path[a.path.length - 1] || a;
    if (!same(end, target)) a.path = route(a, target).slice(1);
  }
  private walk(a: MotionActor, dt: number, reduced: boolean) {
    if (reduced && a.path.length) {
      Object.assign(a, a.path[a.path.length - 1]); a.path = []; a.dir = "down"; return;
    }
    let distance = SPEED * Math.min(dt, 0.1);
    while (distance > 0 && a.path.length) {
      const target = a.path[0], dx = target.x - a.x, dy = target.y - a.y;
      const remaining = Math.abs(dx) + Math.abs(dy);
      a.dir = facing(a, target);
      if (remaining <= distance) { a.x = target.x; a.y = target.y; a.path.shift(); distance -= remaining; }
      else { if (dx) a.x += Math.sign(dx) * distance; else a.y += Math.sign(dy) * distance; distance = 0; }
    }
    if (!a.path.length && a.transfer === null) a.dir = "down";
  }
  private trim(map: Map<string, Owner>) {
    while (map.size > 256) map.delete(map.keys().next().value!);
  }
  private seedOwners(snap: Snapshot) {
    // Authoritative snapshots recover stages skipped while suspended or during a feed reset.
    // A snapshot that predates an already accepted event must not roll its ownership back.
    for (const row of snap.roles) if (row.task?.job_id && row.task.status === "running" && BY_ID[row.id]) {
      const old = this.jobOwners.get(row.task.job_id);
      if (old && old.cursor > snap.cursor) continue;
      const owner = { role: row.id, job: row.task.job_id, kind: row.task.kind,
        ref: `${row.task.ref_type}:${row.task.ref_id}`, at: row.task.updated_at || snap.server_time, cursor: snap.cursor };
      this.jobOwners.set(owner.job, owner);
      if (row.task.ref_type && row.task.ref_id) {
        const before = this.refOwners.get(owner.ref);
        if (!before || before.cursor <= snap.cursor) this.refOwners.set(owner.ref, owner);
      }
    }
  }
}
