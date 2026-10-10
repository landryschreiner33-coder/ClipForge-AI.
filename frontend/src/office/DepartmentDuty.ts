/** Room attendance is decorative coordination; each role retains its authoritative job state. */
import { BY_ID, CAST } from "./cast";
import type { RoleRow } from "./api";

export type OfficeDuty = "work" | "supervising" | "support" | "break" | "quiet";
export interface DepartmentAttendance { attending: boolean; duty: OfficeDuty }
const ROUTINE = new Set(["schedule_tick", "feed_scan", "live_watch", "maintenance", "selftest"]);

function assignedWork(row: RoleRow): boolean {
  const task = row.task;
  const pending = ["waiting", "retrying"].includes(row.state)
    && task && ["queued", "waiting", "retrying"].includes(task.status);
  const attention = row.state === "error" && task && ["failed", "blocked"].includes(task.status);
  if (!task?.job_id || !(pending || attention)) return false;
  // The API does not expose the periodic/manual payload. A concrete reference or repair still identifies
  // substantive work; a bare recurring maintenance/schedule tick should not summon the whole office.
  const reference = task.ref_type && task.ref_id || task.shared?.source_id || task.shared?.project_id
    || task.shared?.clip_id || task.handoff?.from_role;
  return !ROUTINE.has(task.kind) || !!reference;
}

export function departmentAttendance(rows: RoleRow[]): Record<string, DepartmentAttendance> {
  const byId = new Map(rows.map(row => [row.id, row]));
  const busy = new Set(rows.filter(row => BY_ID[row.id]
    && (["working", "reviewing"].includes(row.state) || assignedWork(row))).map(row => BY_ID[row.id].dept));
  return Object.fromEntries(CAST.map(character => {
    const row = byId.get(character.id), state = row?.state || "unavailable";
    const attending = busy.has(character.dept) || ["working", "reviewing", "error"].includes(state);
    let duty: OfficeDuty;
    if (state === "reviewing" || state === "working") {
      // office/view.py marks a manager Working without a task while it watches its department.
      duty = character.rank === "manager" && state === "working" && !row?.task ? "supervising" : "work";
    } else if (["paused", "unavailable", "error"].includes(state)) duty = "quiet";
    else if (!attending) duty = "break";
    else duty = character.rank === "manager" ? "supervising" : "support";
    return [character.id, { attending, duty }];
  }));
}
