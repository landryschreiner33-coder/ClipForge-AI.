import { AnimState, DEPARTMENTS, DepartmentId, RoleId, roleById } from "../robots";
import { OfficeRobot, RunState } from "./officeApi";

/**
 * Where everything sits in the office (reference image A): rooms on a 3x4 grid with slate corridors between them,
 * and the pure rules that place a robot from the snapshot. No randomness and no invented activity: a robot is at
 * its desk, in the Lounge (only while Autopilot is paused or stopped) or reviewing its team's running work.
 */
export type RoomId = DepartmentId | "lounge" | "team" | "devlog";

export interface RoomDef {
  id: RoomId;
  label: string;
  color: string;
  area: string;
  /** Short furniture recipe drawn by rooms.tsx. */
  kit: "lounge" | "boss" | "brain" | "desks" | "studio" | "captions" | "schedule" | "dock" | "team" | "system"
    | "devlog";
}

const dept = (id: DepartmentId) => DEPARTMENTS.find((d) => d.id === id)!;

export const ROOMS: RoomDef[] = [
  { id: "lounge", label: "Lounge", color: "#E8B678", area: "lounge", kit: "lounge" },
  { id: "boss_hub", label: dept("boss_hub").label, color: dept("boss_hub").color, area: "boss", kit: "boss" },
  { id: "brain", label: "Brain Room", color: dept("brain").color, area: "brain", kit: "brain" },
  { id: "discover", label: dept("discover").label, color: dept("discover").color, area: "discover", kit: "desks" },
  { id: "team", label: "Team Workspace", color: "#28D9FF", area: "team", kit: "team" },
  { id: "analyze", label: dept("analyze").label, color: dept("analyze").color, area: "analyze", kit: "desks" },
  {
    id: "clip_studio", label: dept("clip_studio").label, color: dept("clip_studio").color, area: "clip",
    kit: "studio",
  },
  { id: "system", label: "System", color: dept("system").color, area: "system", kit: "system" },
  { id: "caption", label: dept("caption").label, color: dept("caption").color, area: "caption", kit: "captions" },
  { id: "schedule", label: dept("schedule").label, color: dept("schedule").color, area: "schedule", kit: "schedule" },
  { id: "devlog", label: "Dev Log", color: "#9AA3B8", area: "devlog", kit: "devlog" },
  {
    id: "upload_dock", label: dept("upload_dock").label, color: dept("upload_dock").color, area: "upload",
    kit: "dock",
  },
];

export const roomById = (id: string) => ROOMS.find((r) => r.id === id);

/** Members of a department room in desk order: manager first, then its workers. */
export function membersOf(room: RoomId): RoleId[] {
  const d = DEPARTMENTS.find((x) => x.id === room);
  return d ? [d.managerId, ...d.workerIds] : [];
}

export type Placement = { role: RoleId; room: RoomId; sprite: AnimState; robot: OfficeRobot };

/** Which room a robot stands in now, and the sprite state that tells the truth about it. */
export function place(robot: OfficeRobot, run: RunState): Placement | null {
  const role = roleById(robot.role);
  if (!role) return null;
  const home = role.department as RoomId;
  switch (robot.state) {
    case "working": return { role: role.id, room: home, sprite: "work", robot };
    case "waiting": return { role: role.id, room: home, sprite: "waiting", robot };
    case "error": return { role: role.id, room: home, sprite: "error", robot };
    case "monitoring": return { role: role.id, room: home, sprite: "review", robot };
    case "lounge":
      // The backend only says "lounge" while Autopilot is not running; double-check so a stale value cannot put a
      // robot on the sofa while work runs.
      return run === "running" ? { role: role.id, room: home, sprite: "idle", robot }
        : { role: role.id, room: "lounge", sprite: "idle", robot };
    default: return { role: role.id, room: home, sprite: "idle", robot };
  }
}

/** Plain words for a robot's state, used in labels, the list view and the detail panel. */
export const STATE_WORDS: Record<OfficeRobot["state"], string> = {
  working: "Working",
  waiting: "Waiting",
  error: "Problem, retrying",
  idle: "Idle at desk",
  lounge: "Resting in the Lounge",
  monitoring: "Watching the team's work",
};

/** A shape for each state, so status never depends on colour alone. */
export const STATE_SHAPE: Record<OfficeRobot["state"], string> = {
  working: "▶", waiting: "⏸", error: "✕", idle: "•", lounge: "–", monitoring: "◉",
};

/** At most this many robots are drawn in the Lounge; the rest are a count that opens the list. */
export const LOUNGE_SHOWN = 5;
