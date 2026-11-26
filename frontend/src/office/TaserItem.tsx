/** The Taser as a thing on the ship (the owner, 2026-11-26: "make it an actual item you can grab with animations and
 * make sure when you taze them its animated"). It lies on its charger on the Control room floor. Pick it up and it
 * follows the pointer over the ship, swaying in your hand with its prongs crackling; click a robot and the Taser
 * lunges, the robot reacts (taser.ts deals one of nine reactions, StudioScene draws it) and the Taser recharges for a
 * moment. Escape, the charger or the button under the ship puts it back, and it glides home.
 *
 * With a keyboard the charger and the robots are buttons: Enter picks the Taser up, Tab to a robot and Enter zaps it,
 * Escape puts it back. Nothing is sent anywhere and every robot's job carries on. */
import { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent, RefObject, useEffect, useRef,
  useState } from "react";
import { createPortal } from "react-dom";
import { VIEW } from "./world";
import { RECHARGE_MS, ZAP_MS, ZapPicker, ZapReaction, zapSound } from "./taser";

/** The charger, in world units: on the Control room floor, left of COMMAND's platform. */
export const TASER_DOCK = { x: 1252, y: 236, w: 48, h: 30 };
/** Where the Taser's sparking prongs are in its picture (fractions of it), so it zaps right at the pointer. */
const TIP = { x: 3.5 / 32, y: 6.5 / 18 };
const pct = (value: number, total: number) => `${value / total * 100}%`;

export interface ZapFx { kind: ZapReaction; start: number; seed: number }
export interface Burst { key: number; id: string; x: number; y: number; kind: ZapReaction | "miss"; words: string }
type Pt = { x: number; y: number };

/** The Taser in pixel art: yellow and black, silver prongs, a light that is green when charged and amber while it
 * recharges, and two arcs that crackle between the prongs. */
export function TaserArt({ className = "" }: { className?: string }) {
  return <svg className={`taser-art${className ? ` ${className}` : ""}`} viewBox="-6 -2 32 18"
    shapeRendering="crispEdges" aria-hidden="true" focusable="false">
    <polyline className="arc" points="-1,2.5 -4,3.4 -1.5,4.4 -4.5,5.5 -1,6.5" />
    <polyline className="arc arc-2" points="-1,2.5 -3,3.8 -0.5,4.6 -3.5,5.6 -1,6.5" />
    <rect x="0" y="2" width="4" height="1" fill="#cfd6e6" /><rect x="0" y="6" width="4" height="1" fill="#cfd6e6" />
    <rect x="0" y="2" width="1" height="1" fill="#ffffff" /><rect x="0" y="6" width="1" height="1" fill="#ffffff" />
    <polygon points="15,8 21,8 24,15 18,15" fill="#16171d" />
    <polygon points="16,8 20,8 22.5,14 18.8,14" fill="#2b2e3a" />
    <rect x="18" y="10" width="3" height="1" fill="#454a5c" /><rect x="19" y="12" width="3" height="1" fill="#454a5c" />
    <rect x="12" y="8" width="1" height="3" fill="#cfd6e6" /><rect x="12" y="10" width="3" height="1" fill="#cfd6e6" />
    <rect x="3" y="0" width="21" height="9" fill="#16171d" />
    <rect x="4" y="1" width="3" height="7" fill="#2b2e3a" /><rect x="4" y="1" width="3" height="1" fill="#454a5c" />
    <rect x="7" y="1" width="13" height="7" fill="#ffd23f" />
    <rect x="7" y="1" width="13" height="1" fill="#fff0a0" /><rect x="7" y="7" width="13" height="1" fill="#d9a400" />
    <polygon points="11.5,2 9,5 11,5 10,7.5 13.5,4 11.5,4 13,2" fill="#16171d" />
    <rect className="led" x="16" y="3" width="2" height="2" />
    <rect x="20" y="1" width="3" height="7" fill="#2b2e3a" /><rect x="20" y="1" width="3" height="1" fill="#454a5c" />
  </svg>;
}

/** The Taser's state and actions for the ship (OfficeMap). `fx` holds the zaps the ship is drawing. */
export function useTaser({ enabled, sounds, robots, world, name }: {
  enabled: boolean; sounds: boolean;
  robots: RefObject<Map<string, HTMLButtonElement>>; world: RefObject<HTMLDivElement>;
  name: (id: string) => string;
}) {
  const [held, setHeld] = useState(false);
  const [bursts, setBursts] = useState<Burst[]>([]);
  const [said, setSaid] = useState("");
  const [placed, setPlaced] = useState(0);
  const fx = useRef(new Map<string, ZapFx>());
  const picker = useRef<ZapPicker | null>(null);
  if (!picker.current) picker.current = new ZapPicker();
  const hand = useRef<HTMLDivElement>(null), dock = useRef<HTMLButtonElement>(null);
  const pointer = useRef<Pt | null>(null), holding = useRef(false), returning = useRef(false);
  const chargedAt = useRef(0), count = useRef(0), glideUntil = useRef(0), timers = useRef(new Set<number>());
  holding.current = held;

  const later = (fn: () => void, ms: number) => {
    const id = window.setTimeout(() => { timers.current.delete(id); fn(); }, ms);
    timers.current.add(id);
  };
  useEffect(() => () => { for (const id of timers.current) window.clearTimeout(id); }, []);

  /** Puts the Taser's prongs at a point on the screen; a glide takes a quarter second. */
  const aim = (at: Pt, glide = false) => {
    const el = hand.current;
    if (!el) return;
    if (glide) {
      glideUntil.current = performance.now() + 260;
      later(() => { if (performance.now() >= glideUntil.current - 5) el.classList.remove("gliding"); }, 270);
    }
    el.classList.toggle("gliding", glide || performance.now() < glideUntil.current);
    el.style.transform = `translate(${Math.round(at.x - el.offsetWidth * TIP.x)}px, ${
      Math.round(at.y - el.offsetHeight * TIP.y)}px)`;
    el.dataset.shown = "true";
  };
  const onCharger = (): Pt | null => {
    const r = dock.current?.getBoundingClientRect();
    return r && r.width ? { x: r.left + r.width * .16, y: r.top + r.height * .4 } : null;
  };

  const pickUp = (at?: Pt | null) => {
    if (!enabled || holding.current) return;
    // it rises from the charger when the charger is in view (a ship zoomed to another room hides it)
    const from = onCharger(), ship = dock.current?.closest(".office-map")?.getBoundingClientRect();
    const seen = !!from && !!ship && from.x >= ship.left && from.x <= ship.right && from.y >= ship.top
      && from.y <= ship.bottom;
    returning.current = false;
    if (from && seen) aim(from);
    setHeld(true);
    holding.current = true;
    const to = at || pointer.current || (from && seen ? { x: from.x - 24, y: from.y - 36 } : null);
    if (to) requestAnimationFrame(() => aim(to, true));
    if (hand.current) hand.current.dataset.charge = performance.now() < chargedAt.current ? "charging" : "ready";
    setSaid("You picked up the Taser. Choose a robot to zap it. Escape puts it back.");
  };
  const putBack = () => {
    if (!holding.current || returning.current) return;
    returning.current = true;
    const el = hand.current, home = onCharger(), shown = el?.dataset.shown === "true";
    if (shown && home) aim(home, true);
    later(() => {
      if (el) el.dataset.shown = "false";
      returning.current = false; holding.current = false;
      setHeld(false); setPlaced(Date.now());
    }, shown && home ? 260 : 0);
    setSaid("The Taser is back on its charger.");
  };

  const lunge = () => {
    const el = hand.current;
    if (!el) return;
    el.classList.remove("lunge"); void el.offsetWidth; el.classList.add("lunge");
    later(() => el.classList.remove("lunge"), 300);
  };
  /** Zaps a robot: the Taser lunges, the robot plays its reaction and says something, and the Taser recharges.
   * Zapping again before it has recharged only fizzles. */
  const zap = (id: string, fromKeyboard: boolean) => {
    const robot = robots.current?.get(id);
    if (!robot || !holding.current || returning.current) return;
    const now = performance.now(), weak = now < chargedAt.current;
    const kind: ZapReaction = weak ? "fizzle" : picker.current!.next();
    if (!weak) chargedAt.current = now + RECHARGE_MS;
    fx.current.set(id, { kind, start: now, seed: Math.floor(Math.random() * 1e6) });
    const key = ++count.current, words = picker.current!.line(kind);
    const x = robot.offsetLeft + robot.offsetWidth / 2, y = robot.offsetTop + robot.offsetHeight * .35;
    setBursts(list => [...list.filter(b => b.id !== id), { key, id, x, y, kind, words }]);
    later(() => setBursts(list => list.filter(b => b.key !== key)), ZAP_MS[kind] + 500);
    setSaid(`${name(id)}: ${words}`);
    if (sounds) zapSound(kind);
    const el = hand.current;
    if (!el) return;
    if (fromKeyboard || el.dataset.shown !== "true") {
      const r = robot.getBoundingClientRect();
      aim({ x: r.right - r.width * .2, y: r.top + r.height * .55 }, true);
    }
    lunge();
    el.dataset.charge = weak ? "low" : "charging";
    later(() => { if (performance.now() >= chargedAt.current - 5) el.dataset.charge = "ready"; },
      Math.max(120, chargedAt.current - now));
  };
  /** A click on the floor, a room or the Brain while holding the Taser: a spark in the air, nothing opens. */
  const miss = (event: ReactMouseEvent<HTMLElement>) => {
    const box = world.current?.getBoundingClientRect();
    if (!box) return;
    const target = event.currentTarget, keyboard = event.detail === 0;
    const x = keyboard ? target.offsetLeft + target.offsetWidth / 2 : event.clientX - box.left;
    const y = keyboard ? target.offsetTop + target.offsetHeight / 2 : event.clientY - box.top;
    const key = ++count.current;
    setBursts(list => [...list, { key, id: "", x, y, kind: "miss", words: "" }]);
    later(() => setBursts(list => list.filter(b => b.key !== key)), 650);
    if (sounds) zapSound("fizzle");
    lunge();
  };

  const track = (event: ReactPointerEvent) => {
    pointer.current = { x: event.clientX, y: event.clientY };
    if (holding.current && !returning.current) aim(pointer.current);
  };
  const leave = () => {
    pointer.current = null;
    if (holding.current && !returning.current && hand.current) hand.current.dataset.shown = "false";
  };

  useEffect(() => {
    if (enabled) return;
    holding.current = false; returning.current = false;
    setHeld(false); fx.current.clear(); setBursts([]);
  }, [enabled]);
  useEffect(() => {
    if (!held) return;
    const key = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault(); putBack();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
    // putBack reads only refs and setters
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [held]);

  return { held, bursts, said, placed, fx, hand, dock, pickUp, putBack, zap, miss, track, leave };
}
export type Taser = ReturnType<typeof useTaser>;

/** The charger on the Control room floor, with the Taser on it unless you are holding it. */
export function TaserDock({ taser }: { taser: Taser }) {
  const { held, placed } = taser;
  return <button ref={taser.dock} type="button" className="taser-dock" data-empty={held ? "true" : "false"}
    style={{ left: pct(TASER_DOCK.x - VIEW.x, VIEW.w), top: pct(TASER_DOCK.y - VIEW.y, VIEW.h),
      width: pct(TASER_DOCK.w, VIEW.w), height: pct(TASER_DOCK.h, VIEW.h) }}
    aria-label={held ? "Taser charger: put the Taser back" : "Taser charger: pick up the Taser"}
    title={held ? "Put the Taser back" : "Pick up the Taser (just for fun: work carries on)"}
    onClick={(event) => (held ? taser.putBack()
      : taser.pickUp(event.detail ? { x: event.clientX, y: event.clientY } : null))}>
    <span className="taser-pad" aria-hidden="true" />
    {!held && <TaserArt key={placed} className={placed ? "placed" : ""} />}
    <span className="taser-label" aria-hidden="true">{held ? "Put back" : "Taser"}</span>
  </button>;
}

/** The Taser in your hand: it follows the pointer over the ship (drawn above the page, so nothing clips it). */
export function HeldTaser({ taser, width }: { taser: Taser; width: number }) {
  return createPortal(<div ref={taser.hand} className={`taser-held${taser.held ? " in-hand" : ""}`}
    style={{ width, height: Math.round(width * 18 / 32) }} aria-hidden="true"><TaserArt /></div>, document.body);
}

/** The flash and the robot's words over the robot that was zapped (a still spark under Reduced motion). */
export function TaserBursts({ taser }: { taser: Taser }) {
  return <>{taser.bursts.map(b => <span key={b.key} className="taser-zap" data-kind={b.kind}
    data-robot={b.id || undefined} style={{ left: b.x, top: b.y }} aria-hidden="true">
    <svg viewBox="0 0 64 64" width="64" height="64">
      <polyline points="30,2 22,26 34,28 20,62 44,24 32,22 40,2" />
      <polyline className="arc" points="6,30 14,26 10,36 18,32" />
      <polyline className="arc" points="58,30 50,24 54,36 46,32" />
    </svg>
    {b.words && <span className="taser-words">{b.words}</span>}
  </span>)}</>;
}
