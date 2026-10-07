import { CSSProperties, ReactNode } from "react";
import { CoreActivity, CoreChamber } from "../robots";
import { RoomDef } from "./layout";

/**
 * Furniture: plain CSS shapes in the room's corners and along its back wall, kept away from the floor where the
 * robots stand. Purely decorative (aria-hidden); the screens show no numbers, so nothing here can be mistaken for
 * live data.
 */
type F = { k: string; x: number; y: number; w?: number; h?: number; extra?: CSSProperties };

const at = ({ x, y, w, h, extra }: F): CSSProperties => ({
  left: `${x}%`, top: `${y}%`, ...(w !== undefined ? { width: `${w}%` } : {}),
  ...(h !== undefined ? { height: `${h}%` } : {}), ...extra,
});

const KITS: Record<RoomDef["kit"], F[]> = {
  lounge: [
    { k: "rug", x: 22, y: 46, w: 56, h: 40 }, { k: "sofa", x: 26, y: 30, w: 48, h: 16 },
    { k: "table", x: 40, y: 56, w: 20, h: 12 }, { k: "lamp", x: 6, y: 22 }, { k: "plant", x: 88, y: 66 },
    { k: "frame", x: 80, y: 14, w: 12, h: 14 },
  ],
  boss: [
    { k: "screen", x: 18, y: 14, w: 26, h: 18 }, { k: "screen", x: 56, y: 14, w: 26, h: 18 },
    { k: "shelf", x: 2, y: 14, w: 9, h: 48 }, { k: "shelf", x: 89, y: 14, w: 9, h: 48 },
    { k: "plant", x: 14, y: 70 }, { k: "plant", x: 82, y: 70 },
  ],
  brain: [
    { k: "shelf", x: 3, y: 16, w: 10, h: 46 }, { k: "rack", x: 86, y: 18, w: 9, h: 44 }, { k: "plant", x: 78, y: 72 },
  ],
  desks: [
    { k: "screen", x: 30, y: 14, w: 40, h: 18 }, { k: "shelf", x: 3, y: 16, w: 9, h: 44 },
    { k: "plant", x: 88, y: 20 }, { k: "plant", x: 6, y: 74 },
  ],
  studio: [
    { k: "screen", x: 32, y: 14, w: 34, h: 18 }, { k: "reel", x: 6, y: 20 }, { k: "shelf", x: 88, y: 16, w: 9, h: 44 },
    { k: "plant", x: 6, y: 74 },
  ],
  captions: [
    { k: "screen", x: 34, y: 14, w: 30, h: 18, extra: {} }, { k: "shelf", x: 3, y: 16, w: 9, h: 44 },
    { k: "plant", x: 88, y: 70 },
  ],
  schedule: [
    { k: "board", x: 30, y: 12, w: 38, h: 24 }, { k: "clock", x: 80, y: 14 }, { k: "plant", x: 6, y: 72 },
  ],
  dock: [
    { k: "crates", x: 6, y: 34, w: 16, h: 14 }, { k: "conveyor", x: 52, y: 14, w: 42, h: 8 },
    { k: "stripes", x: 0, y: 92, w: 100, h: 8 },
  ],
  team: [
    { k: "rug", x: 14, y: 38, w: 72, h: 50 }, { k: "table", x: 24, y: 52, w: 52, h: 16 },
    { k: "board", x: 34, y: 12, w: 32, h: 18 }, { k: "plant", x: 6, y: 18 }, { k: "plant", x: 90, y: 18 },
  ],
  system: [
    { k: "rack", x: 6, y: 16, w: 10, h: 46 }, { k: "rack", x: 84, y: 16, w: 10, h: 46 },
    { k: "screen", x: 34, y: 14, w: 32, h: 16 },
  ],
  devlog: [
    { k: "terminal", x: 30, y: 14, w: 40, h: 34 }, { k: "door", x: 34, y: 76, w: 32, h: 24 },
    { k: "plant", x: 8, y: 70 }, { k: "plant", x: 86, y: 70 },
  ],
};

export function Furniture({ room, core, reduced }: { room: RoomDef; core?: CoreActivity; reduced: boolean }) {
  return (
    <div className="room-decor" aria-hidden="true">
      {KITS[room.kit].map((f, i) => <span key={i} className={`f f-${f.k}`} style={at(f)} />)}
      {room.kit === "brain" && (
        <span className="f f-core" style={{ left: "50%", top: "6%" }}>
          <CoreChamber scale={1} activity={core || "idle"} reducedMotion={reduced} />
        </span>
      )}
    </div>
  );
}

/** One room: its sign (opens the room's details), its furniture and whatever stands in it. */
export function Room({ room, selected, onOpen, children, count, core, reduced, dim }: {
  room: RoomDef; selected: boolean; onOpen: () => void; children?: ReactNode; count?: string; core?: CoreActivity;
  reduced: boolean; dim: boolean;
}) {
  return (
    <section className={`room kit-${room.kit} ${selected ? "is-selected" : ""} ${dim ? "is-dim" : ""}`}
      style={{ gridArea: room.area, "--accent": room.color } as CSSProperties} aria-label={room.label}
      data-room={room.id}>
      <button type="button" className="room-sign" aria-pressed={selected} onClick={onOpen}
        aria-label={`${room.label}: open details${count ? ` (${count})` : ""}`}>
        <span className="room-sign-text">{room.label}</span>
        {count && <span className="room-count" aria-hidden="true">{count}</span>}
      </button>
      <Furniture room={room} core={core} reduced={reduced} />
      <div className="room-floor">{children}</div>
    </section>
  );
}
