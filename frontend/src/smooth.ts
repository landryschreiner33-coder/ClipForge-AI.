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

/** What a copy does not take over from the original: how far its parts are scrolled and which choices its lists show
 * (both live outside the page's markup). Read while the original is still laid out, put back once the copy is in. */
function looks(el: HTMLElement) {
  const all = [el, ...Array.from(el.querySelectorAll("*"))];
  const scrolled: [number, number, number][] = [], chosen: [number, boolean[]][] = [];
  all.forEach((n, i) => {
    if (n.scrollTop || n.scrollLeft) scrolled.push([i, n.scrollTop, n.scrollLeft]);
    if (n instanceof HTMLSelectElement) chosen.push([i, Array.from(n.options, (o) => o.selected)]);
  });
  return (copy: HTMLElement) => {
    const into = [copy, ...Array.from(copy.querySelectorAll("*"))];
    for (const [i, top, left] of scrolled) {
      into[i].scrollTop = top;
      into[i].scrollLeft = left;
    }
    for (const [i, picks] of chosen) {
      const list = into[i];
      if (list instanceof HTMLSelectElement) picks.forEach((on, k) => { if (list.options[k]) list.options[k].selected = on; });
    }
  };
}

/**
 * `el` is being taken off the page by React (its ref is let go just before): a copy of it plays `exit` where it was,
 * then goes. The copy is inert and hidden from screen readers, takes no clicks, and has no ids or field names (so it
 * never stands in for the real thing); it keeps the original's classes so it looks the same, so code looking for an
 * open pop-up skips `.leaving` (Office, Studio, menus). It shows what the original showed, scrolled the same way. A
 * pop-up holding a frame, a video or a canvas closes at once: a copy of those would load again or show blank.
 */
function leave(el: HTMLElement, exit: Exit) {
  const parent = el.parentNode, next = el.nextSibling;
  if (!parent || reduced() || typeof el.animate !== "function") return;
  if (el.querySelector("iframe, video, audio, canvas, object, embed")) return;
  const restore = looks(el);
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
    restore(copy);
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

/** How far a row is shown away from its place right now by a slide of its own (its animated `translate`), in px. */
function shift(item: Element) {
  const t = getComputedStyle(item).translate;
  if (!t || t === "none") return 0;
  const parts = t.split(" ");
  return parts.length > 1 ? parseFloat(parts[1]) || 0 : 0;
}

/**
 * The items of `list` (its children, the same elements from one render to the next: keyed rows) slide to their new
 * places when their order changes, instead of jumping: each row's place is measured before and after (without the
 * slide it may still be playing), then it eases from where it is shown to its new place (FLIP). Only a change of
 * order slides; a row that grows, a new row or a resized window does not. A move during a slide carries on from
 * where each row is shown, and rows whose place did not change keep their slide.
 */
export function useSlide(list: RefObject<HTMLElement>) {
  const before = useRef(new Map<Element, number>());
  const order = useRef<Element[]>([]);
  const slides = useRef(new WeakMap<Element, Animation>());
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
    const shown = new Map(items.map((item) => [item, item.getBoundingClientRect().top - top]));
    const now = new Map(items.map((item) => [item, shown.get(item)! - shift(item)]));
    if (moved && !reduced()) {
      for (const item of kept) {
        const from = before.current.get(item)!, to = now.get(item)!;
        if (Math.abs(from - to) < 1 || typeof (item as HTMLElement).animate !== "function") continue;
        // from where the row is shown on screen this moment (its old place plus what is left of a slide)
        const dy = from - to + (shown.get(item)! - to);
        slides.current.get(item)?.cancel();
        slides.current.set(item, (item as HTMLElement).animate([{ translate: `0 ${dy}px` }, { translate: "0 0" }],
          { duration: 280, easing: EASE }));
      }
    }
    before.current = now;
    order.current = items;
  });
}
