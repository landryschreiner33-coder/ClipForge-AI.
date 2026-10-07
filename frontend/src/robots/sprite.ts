/**
 * Composes a role's art into SVG path runs for a given direction/state/frame.
 * Results are cached, so animating many sprites only costs a lookup per frame.
 *
 * Fallback rules (documented in one place):
 * - unknown role id  -> renders nothing (`renderFrame` returns null)
 * - unknown direction -> "down"; unknown state -> "idle" (see registry.resolve*)
 * - frame index wraps modulo the state's frame count
 * - every state is supported by every role: shared poses come from rig.poseFor and each role's
 *   art only adds its signature work motion; a role with no special work drawing just shows its
 *   working arm pose with equipment, so identity is never lost.
 * - "left" is the "right" profile mirrored, except text decals which are re-stamped unmirrored.
 */
import { ART } from "./art";
import { Painter, grey, layerToPaths, stampText, textWidth, W, type LayerName, type PathRun } from "./pixel";
import { type AnimState, type Direction, roleById, resolveDirection, resolveState } from "./registry";
import { drawRobot, makeKit, poseFor, type View } from "./rig";

export interface SpriteFrame {
  layers: Record<LayerName, PathRun[]>;
  grey: boolean;
  /** True when the frame contains the tintable task card. */
  hasCard: boolean;
}

const cache = new Map<string, SpriteFrame>();

export function viewFor(dir: Direction): View {
  return dir === "down" ? "front" : dir === "up" ? "back" : "side";
}

export function frameCount(roleId: string, state: AnimState): number {
  return roleById(roleId)?.anim[resolveState(state)].frames ?? 1;
}

export function renderFrame(roleId: string, dirIn: string, stateIn: string, frameIn: number): SpriteFrame | null {
  const role = roleById(roleId);
  if (!role) return null;
  const dir = resolveDirection(dirIn);
  const state = resolveState(stateIn);
  const n = role.anim[state].frames;
  const frame = ((Math.floor(frameIn) % n) + n) % n;
  const key = `${role.id}|${dir}|${state}|${frame}`;
  const hit = cache.get(key);
  if (hit) return hit;

  const painter = new Painter();
  const pose = poseFor(state, frame);
  drawRobot(painter, ART[role.id], role, makeKit(role), viewFor(dir), pose);
  const layers = painter.layers;
  const mirror = dir === "left";
  if (mirror) for (const l of Object.values(layers)) l.mirror();
  for (const d of painter.decals) {
    const x = mirror ? W - d.x - textWidth(d.text) : d.x;
    stampText(layers[d.layer], x, d.y, d.text, d.color);
  }
  if (pose.grey) for (const l of Object.values(layers)) l.map(grey);
  const out: SpriteFrame = {
    layers: {
      back: layerToPaths(layers.back),
      base: layerToPaths(layers.base),
      card: layerToPaths(layers.card),
      over: layerToPaths(layers.over),
    },
    grey: pose.grey,
    hasCard: pose.card !== null,
  };
  cache.set(key, out);
  return out;
}
