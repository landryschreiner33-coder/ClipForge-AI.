/** Visual choreography only. Durable jobs are never delayed or changed by a walk or a document transfer. */
import { BY_ID, CAST, Dir } from "./cast";
import { OfficeEvent, RoleRow, Snapshot } from "./api";
import { BreakActivity, Pt, REST_SEAT, roomOf, route, STATION, SUPERVISE } from "./world";
import { LoungeLife } from "./LoungeLife";
import { departmentAttendance, OfficeDuty } from "./DepartmentDuty";
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
  started: number; until: number; fromJobs: string[]; toJobs: string[];
}
interface HandoffRoute {
  event: OfficeEvent; path: string[]; step: number; jobs: string[]; until: number;
}
interface Owner { role: string; job: string; kind: string; ref: string; at: number; cursor: number }
const SPEED = 130;
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

export function placements(rows: RoleRow[]): Record<string, { at: Pt; lounge: boolean; duty: OfficeDuty }> {
  const attendance = departmentAttendance(rows);
  return Object.fromEntries(CAST.map(c => {
    const { attending, duty } = attendance[c.id], lounge = !attending;
    const at = lounge ? REST_SEAT[c.id] : duty === "supervising" ? SUPERVISE[c.id] || STATION[c.id] : STATION[c.id];
    return [c.id, { at, lounge, duty }];
  }));
}

export class OfficeMotion {
  readonly actors = new Map<string, MotionActor>();
  private rows = new Map<string, RoleRow>();
  private targets: ReturnType<typeof placements> = {};
  private transfers = new Map<number, Transfer>();
  private handoffs = new Map<number, HandoffRoute>();
  private seen = new Set<number>();
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
      const transfer = actor.transfer === null ? null : this.transfers.get(actor.transfer);
      if (transfer && (this.blocked(actor.id)
        || this.foreignWork(actor.id, actor.id === transfer.from ? transfer.fromJobs : transfer.toJobs))) {
        this.cancel(transfer.id);
      }
      if (this.blocked(actor.id)) actor.reaction = null;
      if (actor.transfer !== null) continue;
      // Actual work is already under way: show it in its own room immediately. Supporting peers may commute.
      this.go(actor, target, reduced || ["working", "reviewing"].includes(this.rows.get(actor.id)?.state || ""));
      this.faceBreak(actor);
    }
    this.seedOwners(snap);
    this.trim(this.jobOwners); this.trim(this.refOwners);
  }

  /** Connection recovery uses the latest state, with no replay of transfers missed while offline. */
  resync(snap: Snapshot) {
    this.clearTransfers();
    this.cutoff = snap.cursor;
    this.seen.clear();
    this.jobOwners.clear(); this.refOwners.clear();
    this.reconcile(snap, true);
  }

  react(id: string, pose: Pose, now: number) {
    const a = this.actors.get(id);
    if (a && !this.blocked(id)) a.reaction = { pose, until: now + 2200 };
  }

  events(events: OfficeEvent[], serverTime: number, now: number, reduced: boolean) {
    for (const event of events) {
      if (event.id <= this.cutoff || this.seen.has(event.id) || serverTime - event.at > 30
        || event.at > serverTime + 5) continue;
      this.seen.add(event.id);
      const recordedPath = Object.prototype.hasOwnProperty.call(event.data || {}, "handoff_path");
      const explicit = this.handoffPath(event);
      if (explicit) this.queueHandoff(event, explicit, now, reduced);
      else if (!recordedPath && event.type === "report" && !event.data?.routine
        && BY_ID[event.data?.worker] && BY_ID[event.role])
        this.queueHandoff(event, [event.data.worker, event.role], now, reduced);
      if (!event.job_id || !BY_ID[event.role] || event.data?.routine) continue;
      if (event.type !== "job_started" && event.type !== "job_stage") continue;
      const previous = this.jobOwners.get(event.job_id);
      const ref = `${event.ref_type}:${event.ref_id}`;
      if (previous && (event.id <= previous.cursor || event.at < previous.at)) continue;
      if (previous && (previous.kind !== event.kind || previous.ref !== ref)) continue;
      if (!recordedPath && event.type === "job_stage" && previous && previous.role !== event.role) {
        // Older feeds still identify real stage changes. Preserve the cast's reporting hierarchy instead of
        // sending a worker straight across departments. Only explicit recorded checkpoints visit COMMAND.
        this.queueHandoff(event, this.stagePath(previous.role, event.role), now, reduced);
      } else if (!recordedPath && event.type === "job_started" && event.ref_type && event.ref_id) {
        const before = this.refOwners.get(`${event.ref_type}:${event.ref_id}`);
        if (before && before.job !== event.job_id && before.cursor < event.id && event.at - before.at <= 30
          && event.at >= before.at && CROSS_JOB[before.kind]?.includes(event.kind)) {
          this.queueHandoff(event, this.stagePath(before.role, event.role), now, reduced, before.job);
        }
      }
      const owner = { role: event.role, job: event.job_id, kind: event.kind, ref, at: event.at, cursor: event.id };
      this.jobOwners.set(event.job_id, owner);
      if (event.ref_type && event.ref_id) this.refOwners.set(`${event.ref_type}:${event.ref_id}`, owner);
    }
    while (this.seen.size > 512) this.seen.delete(this.seen.values().next().value!);
    this.startHandoffs(now, reduced);
    this.trim(this.jobOwners); this.trim(this.refOwners);
  }

  tick(dt: number, now: number, reduced: boolean, frozen: boolean) {
    if (frozen) return;
    if (!reduced) this.lounge.tick(dt, this.actors.values());
    for (const a of this.actors.values()) {
      if (a.reaction && a.reaction.until < now) a.reaction = null;
      // Individually paused/unavailable workers may finish returning to a reserved resting place,
      // but only eligible workers rotate through decorative activities once they arrive.
      if (a.transfer === null) this.go(a, this.destination(a.id), reduced || this.atWork(a.id));
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
        this.cancel(tr.id, true);
      }
    }
    this.startHandoffs(now, reduced);
    // Every completed transfer returns to the latest actual destination, without waiting for another poll.
    for (const a of this.actors.values()) if (a.transfer === null) {
      this.go(a, this.destination(a.id), reduced || this.atWork(a.id)); this.faceBreak(a);
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
    return a.reaction?.pose || (this.duty(a) === "supervising" ? "idle" : POSE[state]);
  }

  posture(a: MotionActor): RobotPosture {
    if (a.path.length || a.transfer !== null || a.reaction) return "stand";
    if (this.targets[a.id]?.lounge && same(a, this.destination(a.id))) {
      return this.breakActivity(a) ? this.lounge.spot(a.id)?.posture || "rest" : "rest";
    }
    if (!this.targets[a.id]?.lounge && this.duty(a) !== "supervising" && same(a, STATION[a.id])
      && this.rows.get(a.id)?.state !== "error") return "desk";
    return "stand";
  }

  duty(a: MotionActor): OfficeDuty {
    return this.targets[a.id]?.lounge && this.canBreak(a.id) ? "break" : this.targets[a.id]?.duty || "quiet";
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
      id: tr.id, from: this.actors.get(tr.from)!, to: this.actors.get(tr.to)!,
      progress: Math.min(1, Math.max(0, 1 - (tr.until - now) / 700)),
    }));
  }

  activeTransfer(): { from: string; to: string; phase: Transfer["phase"]; card: WorkCard } | null {
    const all = [...this.transfers.values()], tr = all[all.length - 1];
    return tr ? { from: tr.from, to: tr.to, phase: tr.phase, card: tr.card } : null;
  }
  isSender(a: MotionActor): boolean {
    return a.transfer !== null && this.transfers.get(a.transfer)?.from === a.id;
  }

  clearTransfers() {
    for (const id of [...this.transfers.keys()]) this.cancel(id);
    this.handoffs.clear();
  }

  private handoffPath(event: OfficeEvent): string[] | null {
    const path = event.data?.handoff_path;
    if (!Array.isArray(path) || path.length < 2 || path.length > 5 || event.data?.routine
      || !path.every(id => typeof id === "string" && BY_ID[id])) return null;
    const consultation = ["brain_consultation_done", "brain_consultation_failed"].includes(event.type)
      && typeof event.data?.consultation_id === "string" && !!event.data.consultation_id;
    if (!event.job_id && !consultation) return null;
    if (!["report", "decision", "job_started", "job_stage", "brain_consultation_done",
      "brain_consultation_failed"].includes(event.type)) return null;
    return path.filter((id, i) => !i || id !== path[i - 1]);
  }

  private stagePath(from: string, to: string): string[] {
    if (BY_ID[from].dept === BY_ID[to].dept) return [from, to];
    return [from, BY_ID[from].manager, BY_ID[to].manager, to]
      .filter((id, i, path) => id && (!i || id !== path[i - 1]));
  }

  private queueHandoff(event: OfficeEvent, path: string[], now: number, reduced: boolean, predecessor = "") {
    if (path.length < 2 || this.handoffs.has(event.id)) return;
    if (reduced) return;
    // Animate only a small, fresh window. Overflow remains visible in Activity rather than being replayed as work.
    if (this.handoffs.size >= 24) return;
    const consultation = event.data?.consultation_id;
    const jobs = [predecessor, event.job_id,
      typeof consultation === "string" && consultation ? `consultation:${consultation}` : ""].filter(Boolean);
    this.handoffs.set(event.id, { event, path, step: 0, jobs, until: now + 30000 });
  }

  private startHandoffs(now: number, reduced: boolean) {
    const reserved = new Set<string>();
    for (const [id, handoff] of this.handoffs) {
      if (this.transfers.has(id)) {
        handoff.path.forEach(role => reserved.add(role)); continue;
      }
      const from = handoff.path[handoff.step], to = handoff.path[handoff.step + 1];
      if (reduced || now > handoff.until || !to || this.blocked(from) || this.blocked(to)
        || this.foreignWork(from, handoff.jobs) || this.foreignWork(to, handoff.jobs)) {
        this.handoffs.delete(id); continue;
      }
      // A later stage cannot take the same manager/director before the earlier report reaches them.
      // Independent departments may still transfer concurrently when their recorded routes do not overlap.
      const waiting = handoff.path.some(role => reserved.has(role));
      handoff.path.forEach(role => reserved.add(role));
      if (waiting) continue;
      if (this.actors.get(from)?.transfer !== null || this.actors.get(to)?.transfer !== null) continue;
      this.transfer(from, to, handoff.event, now, false, handoff.jobs);
    }
  }

  private transfer(from: string, to: string, event: OfficeEvent, now: number, reduced: boolean, jobs: string[]) {
    const sender = this.actors.get(from), receiver = this.actors.get(to);
    if (!sender || !receiver || from === to || this.blocked(from) || this.blocked(to)) return;
    const fromJobs = jobs, toJobs = jobs;
    if (this.foreignWork(from, fromJobs) || this.foreignWork(to, toJobs)) return;
    if (reduced) { this.react(to, "review", now); return; }
    if (sender.transfer !== null || receiver.transfer !== null) return;
    this.lounge.release(from); this.lounge.release(to);
    const card: WorkCard = { job_id: event.job_id, kind: event.kind, ref_type: event.ref_type,
      ref_id: event.ref_id, state: event.data?.state || "stage", summary: event.message, from, to };
    const station = STATION[to], room = roomOf(station)!;
    // The confirmed recipient starts its step in its own office, even if the previous snapshot had it on break.
    if (roomOf(receiver)?.id !== room.id) {
      receiver.x = station.x; receiver.y = station.y; receiver.path = [];
    }
    const side = station.x - room.x > room.w / 2 ? -1 : 1;
    const meet = { x: station.x, y: station.y + 9 };
    const offer = { x: station.x + side * 34, y: station.y + 9 };
    this.go(sender, offer, false); this.go(receiver, meet, false);
    sender.card = card; receiver.card = null;
    sender.transfer = event.id; receiver.transfer = event.id;
    sender.reaction = null; receiver.reaction = null;
    this.transfers.set(event.id, { id: event.id, from, to, card, phase: "approach", started: now, until: 0,
      fromJobs, toJobs });
  }

  private cancel(id: number, completed = false) {
    const tr = this.transfers.get(id);
    if (!tr) return;
    for (const who of [tr.from, tr.to]) {
      const a = this.actors.get(who)!;
      if (a.transfer !== id) continue;
      a.transfer = null; a.card = null; a.path = [];
      this.lounge.sync(who, this.targets[who]?.lounge || false, this.canBreak(who));
    }
    this.transfers.delete(id);
    const handoff = this.handoffs.get(id);
    if (completed && handoff && ++handoff.step < handoff.path.length - 1) return;
    this.handoffs.delete(id);
  }

  private blocked(id: string) { return ["paused", "unavailable"].includes(this.rows.get(id)?.state || "unavailable"); }
  private atWork(id: string) { return ["working", "reviewing"].includes(this.rows.get(id)?.state || ""); }
  private foreignWork(id: string, allowed: string[]) {
    const row = this.rows.get(id);
    if (row?.task?.kind === "brain_consultation" && row.task.status === "running" && this.atWork(id))
      return !row.task.consultation_id || !allowed.includes(`consultation:${row.task.consultation_id}`);
    return !!row?.task?.job_id && row.task.status === "running" && ["working", "reviewing"].includes(row.state)
      && !allowed.includes(row.task.job_id);
  }
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
    } else if (!a.path.length && a.transfer === null && !a.reaction && this.duty(a) === "supervising"
      && same(a, this.destination(a.id))) {
      const peers = CAST.filter(c => c.dept === BY_ID[a.id].dept && c.id !== a.id);
      const workers = peers.filter(c => ["working", "reviewing"].includes(this.rows.get(c.id)?.state || ""));
      const focus = workers.length ? workers : peers;
      const points = focus.map(c => {
        const peer = this.actors.get(c.id);
        return peer && roomOf(peer)?.id === c.room ? peer : STATION[c.id];
      });
      const center = points.length ? { x: points.reduce((sum, p) => sum + p.x, 0) / points.length,
        y: points.reduce((sum, p) => sum + p.y, 0) / points.length } : STATION[a.id];
      a.dir = facing(a, center);
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
        ref: `${row.task.ref_type}:${row.task.ref_id}`, at: row.task.updated_at || snap.server_time,
        cursor: snap.cursor };
      this.jobOwners.set(owner.job, owner);
      if (row.task.ref_type && row.task.ref_id) {
        const before = this.refOwners.get(owner.ref);
        if (!before || before.cursor <= snap.cursor) this.refOwners.set(owner.ref, owner);
      }
    }
  }
}
