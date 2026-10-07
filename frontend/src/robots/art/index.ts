/** Lookup table: role id -> art definition. */
import type { RoleId } from "../registry";
import type { RobotDef } from "../rig";
import { DIRECTOR_ART } from "./director";
import { MANAGER_ART } from "./managers";
import { WORKER_ART } from "./workers";

export const ART: Record<RoleId, RobotDef> = { ...DIRECTOR_ART, ...MANAGER_ART, ...WORKER_ART };

/** Where each role's art lives (used by the manifest and the dev gallery). */
export const ART_SOURCES: Record<RoleId, string> = Object.fromEntries(
  (Object.keys(ART) as RoleId[]).map((id) => [
    id,
    `frontend/src/robots/art/${id in DIRECTOR_ART ? "director" : id in MANAGER_ART ? "managers" : "workers"}.ts#${id}`,
  ]),
) as Record<RoleId, string>;
