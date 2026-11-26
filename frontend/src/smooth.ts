/**
 * Smooth goings and changes of place (the owner, 2026-11-26: smooth out what still jumps, without a new animation
 * library). Pop-ups already ease in with CSS (space.css, "pop-ups"); here they ease out, and list items that change
 * places slide there. Both use the browser's own animations (Web Animations), like the page arrivals in
 * transitions.ts, so the demo recorder and the browser checks see them (document.getAnimations()), and both are
 * instant under Reduced motion. Nothing waits for them: what closed is gone for the app at once (focus, clicks and
 * screen readers move on), and only a look-alike copy, which nothing can reach, fades away.
 */
import { RefCallback, RefObject, useCallback, useLayoutEffect, useRef } from "react";

const EASE = "cubic-bezier(0.2, 0.75, 0.25, 1)";
const reduced = () => document.documentElement.dataset.motion === "reduced";

export type Exit = "dialog" | "menu" | "drawer" | "backdrop" | "toast";
/** How each kind of pop-up goes: a dialog fades as its box sinks a little, a menu fades and shrinks a touch, the
 * small-window menu slides back to the left, a backdrop fades, a note fades as it drops. */
const EXIT: Record<Exit, { ms: number; frames: Keyframe[]; inner?: [string, Keyframe[]] }> = {
  dialog: { ms: 160, frames: [{ opacity: 1 }, { opacity: 0 }],
    inner: [".dialog", [{ translate: "0 0", scale: "1" }, { translate: "0 8px", scale: "0.98" }]] },
  menu: { ms: 120, frames: [{ opacity: 1, scale: "1" }, { opacity: 0, scale: "0.97" }] },
  drawer: { ms: 200, frames: [{ translate: "0 0" }, { translate: "-100% 0" }] },
  backdrop: { ms: 200, frames: [{ opacity: 1 }, { opacity: 0 }] },
  toast: { ms: 200, frames: [{ opacity: 1, translate: "0 0" }, { opacity: 0, translate: "0 10px" }] },
};

/**
 * `el` was just taken off the page by React: a copy of it plays `exit` where it was, then goes. The copy is inert and
 * hidden from screen readers, takes no clicks, and has no ids or field names (so it never stands in for the real
 * thing). A pop-up holding a frame, a video or a canvas closes at once: a copy of those would load again or show blank.
 */
function leave(el: HTMLElement, exit: Exit) {
  const parent = el.parentNode, next = el.nextSibling;
  if (!parent || reduced() || typeof el.animate !== "function") return;
  if (el.querySelector("iframe, video, audio, canvas, object, embed")) return;
  const copy = el.cloneNode(true) as HTMLElement;
  for (const n of [copy, ...Array.from(copy.querySelectorAll("[id], [name]"))]) {
    n.removeAttribute("id");
    n.removeAttribute("name");
  }
  copy.setAttribute("inert", "");
  copy.setAttribute("aria-hidden", "true");
  copy.classList.add("leaving");
  copy.style.pointerEvents = "none";
  // React removes `el` later in the same update; the copy takes its place before the page is painted
  queueMicrotask(() => {
    // still on the page (React kept it, or this was React's trial unmount while developing), or its place is gone
    // too (a whole page left): nothing to show
    if (el.isConnected || !parent.isConnected) return;
    parent.insertBefore(copy, next && next.parentNode === parent ? next : null);
    const { ms, frames, inner } = EXIT[exit];
    const done = copy.animate(frames, { duration: ms, easing: EASE, fill: "forwards" });
    const box = inner && copy.querySelector<HTMLElement>(inner[0]);
    box?.animate(inner![1], { duration: ms, easing: EASE, fill: "forwards" });
    done.finished.then(() => copy.remove(), () => copy.remove());
  });
}

/**
 * A ref for a pop-up that should ease out when it closes (`exit` says how). `also` is the component's own ref for the
 * same element, if it has one. The ref is stable, so React only calls it when the element comes and goes.
 */
export function useLeave<T extends HTMLElement>(exit: Exit, also?: { current: T | null }): RefCallback<T> {
  const node = useRef<T | null>(null);
  const own = useRef(also);
  own.current = also;
  return useCallback((el: T | null) => {
    if (own.current) own.current.current = el;
    if (el) {
      node.current = el;
      return;
    }
    const was = node.current;
    node.current = null;
    if (was) leave(was, exit);
  }, [exit]);
}

/**
 * The items of `list` (its children, the same elements from one render to the next: keyed rows) slide to their new
 * places when their order changes, instead of jumping: each is measured before and after, then eased from where it
 * was (FLIP). Only a change of order slides; a row that grows, a new row or a resized window does not.
 */
export function useSlide(list: RefObject<HTMLElement>) {
  const before = useRef(new Map<Element, number>());
  const order = useRef<Element[]>([]);
  useLayoutEffect(() => {
    const el = list.current;
    if (!el) {
      before.current = new Map();
      order.current = [];
      return;
    }
    const items = Array.from(el.children);
    const kept = items.filter((item) => before.current.has(item));
    const was = order.current.filter((item) => kept.includes(item));
    const moved = kept.some((item, i) => was[i] !== item);
    const top = el.getBoundingClientRect().top;
    const now = new Map(items.map((item) => [item, item.getBoundingClientRect().top - top]));
    if (moved && !reduced()) {
      for (const item of kept) {
        const dy = before.current.get(item)! - now.get(item)!;
        if (Math.abs(dy) < 1 || typeof (item as HTMLElement).animate !== "function") continue;
        (item as HTMLElement).animate([{ translate: `0 ${dy}px` }, { translate: "0 0" }],
          { duration: 280, easing: EASE });
      }
    }
    before.current = now;
    order.current = items;
  });
}
