/** Public surface of the robot crew module. */
export {
  ROLES,
  CORE,
  DEPARTMENTS,
  DIRECTIONS,
  ANIM_STATES,
  roleById,
  departmentById,
  validateRegistry,
  resolveDirection,
  resolveState,
} from "./registry";
export type {
  RoleId,
  Rank,
  DepartmentId,
  Direction,
  AnimState,
  AnimTiming,
  RolePalette,
  RobotRole,
  Department,
  CoreActivity,
} from "./registry";
export { RobotSprite, RobotPortrait, CoreChamber, DEFAULT_CARD, usePrefersReducedMotion } from "./RobotSprite";
export type { RobotSpriteProps, RobotPortraitProps, CoreChamberProps } from "./RobotSprite";
export { TeamRoster } from "./TeamRoster";
export { renderFrame, frameCount } from "./sprite";
export { ART_SOURCES } from "./art";
