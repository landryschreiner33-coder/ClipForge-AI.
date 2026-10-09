/** Plain Canvas compatibility scene: the same floor plan, seats and transfers without a graphics context. */
import { BY_ID, CAST } from "./cast";
import { Snapshot } from "./api";
import { drawRobot, ROOM_ACCENT, spriteCanvas } from "./draw";
import { CORE_AT, REST_SEAT, ROBOT_SCALE, ROOMS, STATION, WORLD } from "./world";
import { FRAMES, frameMs } from "./sprites";
import type { SceneActor } from "./StudioScene";
import type { DocumentPass } from "./OfficeMotion";

export class LivingFallback {
  private floor = document.createElement("canvas");
  constructor(private ctx: CanvasRenderingContext2D) {
    this.floor.width = WORLD.w; this.floor.height = WORLD.h;
    const c = this.floor.getContext("2d")!;
    c.fillStyle = "#243348"; c.fillRect(0, 0, WORLD.w, WORLD.h);
    for (const room of ROOMS) {
      c.fillStyle = "#121c2c"; c.fillRect(room.x, room.y, room.w, room.h);
      c.fillStyle = room.id === "lounge" ? "#35443f" : "#354151";
      c.fillRect(room.x + 4, room.y + 14, room.w - 8, room.h - 18);
      c.fillStyle = ROOM_ACCENT[room.id]; c.fillRect(room.x + 4, room.y + 11, room.w - 8, 2);
      c.fillStyle = "#293646";
      for (let y = room.y + 30; y < room.y + room.h - 4; y += 16) c.fillRect(room.x + 4, y, room.w - 8, 1);
    }
    for (const character of CAST) {
      const rest = REST_SEAT[character.id], desk = STATION[character.id];
      c.fillStyle = "#253443"; c.fillRect(rest.x - 16, rest.y - 29, 32, 30);
      c.fillStyle = "#688777"; c.fillRect(rest.x - 14, rest.y - 27, 28, 14);
      c.fillStyle = "#203042"; c.fillRect(desk.x - 13, desk.y - 32, 26, 34);
      c.fillStyle = "#647c8b"; c.fillRect(desk.x - 11, desk.y - 30, 22, 17);
      c.fillStyle = "#b69c7d"; c.fillRect(desk.x - 29, desk.y - 25, 58, 8);
      c.fillStyle = "#19283b"; c.fillRect(desk.x - 13, desk.y - 47, 26, 19);
      c.fillStyle = "#667e92"; c.fillRect(desk.x - 12, desk.y - 46, 24, 1);
    }
  }
  draw(snap: Snapshot, actors: SceneActor[], time: number, still: boolean, busy: boolean, passes: DocumentPass[]) {
    const c = this.ctx; c.imageSmoothingEnabled = false; c.drawImage(this.floor, 0, 0);
    for (const a of actors) {
      const character = BY_ID[a.id], count = FRAMES[a.pose].n;
      const frame = still ? 0 : Math.floor(time / (frameMs(character, a.pose) || 400)) % count;
      c.save(); c.translate(Math.round(a.x), Math.round(a.y)); c.scale(ROBOT_SCALE, ROBOT_SCALE);
      if (a.posture === "stand" || !a.posture) drawRobot(c, a.id, 0, 0, a.dir, a.pose, frame, a.selected);
      else {
        // Retain the original identity's upper sprite, with authored bent legs under its seated torso.
        c.drawImage(spriteCanvas(a.id, a.dir, a.pose, frame), 0, 0, 48, 44, -24, -49, 48, 37);
        c.fillStyle = character.palette.shade; c.fillRect(-11, -13, 9, 8); c.fillRect(3, -13, 9, 8);
        c.fillStyle = character.palette.trimDark; c.fillRect(-13, -5, 12, 4); c.fillRect(2, -5, 12, 4);
      }
      c.restore();
    }
    // Foreground desktop covers the seated lap while hands and screen remain visible.
    for (const a of actors) if (a.posture === "desk") {
      c.fillStyle = "#c6ac88"; c.fillRect(a.x - 29, a.y - 21, 58, 7);
      c.fillStyle = "#8a7057"; c.fillRect(a.x - 29, a.y - 14, 58, 5);
      c.fillStyle = "#596c79"; c.fillRect(a.x - 11, a.y - 20, 22, 3);
    }
    const paused = snap.run.state === "paused" || snap.brain?.state === "paused";
    const phase = still || paused ? 0 : time / (busy ? 650 : 3200);
    const x = CORE_AT.x, y = CORE_AT.y - 59 + Math.round(Math.sin(phase) * 2);
    c.fillStyle = "#263447"; c.fillRect(x - 35, CORE_AT.y - 11, 70, 11);
    c.fillStyle = busy ? "#bdabed" : "#8c88b3";
    for (const side of [-1, 1]) {
      c.fillRect(x + side * 5 - (side < 0 ? 28 : 0), y - 22, 28, 42);
      c.fillRect(x + side * 5 - (side < 0 ? 33 : -3), y - 12, 24, 30);
    }
    c.strokeStyle = busy ? "#86eadb" : "#619baf"; c.lineWidth = 1;
    c.beginPath(); c.ellipse(x, y, 57, 18, 0, 0, Math.PI * 2); c.stroke();
    for (let i = 0; i < 3; i++) {
      const angle = phase + i * Math.PI * 2 / 3;
      c.fillStyle = ["#e8d394", "#aaacf0", "#80c8cb"][i];
      c.fillRect(Math.round(x + Math.cos(angle) * 57) - 1, Math.round(y + Math.sin(angle) * 18) - 1, 3, 3);
    }
    for (const pass of passes) {
      const xx = Math.round(pass.from.x + (pass.to.x - pass.from.x) * pass.progress);
      const yy = Math.round(pass.from.y + (pass.to.y - pass.from.y) * pass.progress - 22);
      c.fillStyle = "#1a2637"; c.fillRect(xx - 7, yy - 7, 14, 13);
      c.fillStyle = "#f0e3c4"; c.fillRect(xx - 6, yy - 6, 12, 11);
      c.fillStyle = "#6d9fab"; c.fillRect(xx - 3, yy - 3, 7, 2);
    }
  }
}
