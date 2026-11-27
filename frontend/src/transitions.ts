/**
 * Smooth arrivals (the owner, 2026-11-20: "when you swich tabs have it be a smotth transition"). A new page, or the
 * part of a page under its tabs, fades in and rises a little; what loads into it a moment later (the list that takes
 * the place of "Loading…") fades in too. Nothing waits for it: the new content is there at once (focus, reading order
 * and clicks are unchanged) and only its look eases in. Under Reduced motion it is instant.
 */

const EASE = "cubic-bezier(0.2, 0.75, 0.25, 1)";
/** How long after an arrival what loads into it still fades in, ms. */
const SETTLE = 1200;

const reduced = () => document.documentElement.dataset.motion === "reduced";

let settling: MutationObserver | null = null;

/**
 * Fade `els` in: "page" for a new place in the app, "tab" for new content under the same tabs. With `settle`, what
 * is added inside them or beside them during the next moment fades in as well (only the latest arrival is watched).
 */
export function arrive(els: Element[], how: "page" | "tab", settle = true) {
  if (reduced()) return;
  for (const el of els) {
    if (typeof (el as HTMLElement).animate !== "function") continue;
    // a dialog or panel fixed to the window keeps its place: content holding one only fades
    const fixed = !!el.querySelector(".dialog-bg:not(.leaving), .customize, .drawer-bg:not(.leaving)");
    const rise = how === "page" ? 14 : 8;
    (el as HTMLElement).animate(fixed
      ? [{ opacity: 0 }, { opacity: 1 }]
      : [{ opacity: 0, transform: `translateY(${rise}px)` }, { opacity: 1, transform: "none" }],
    { duration: how === "page" ? 340 : 260, easing: EASE });
  }
  if (settle) settleIn(els);
}

/** For a moment after an arrival, an element put in (or beside) what arrived fades in; only its opacity changes. */
function settleIn(els: Element[]) {
  // an older arrival's content is no longer news (disconnecting also drops what it had not handled yet)
  settling?.disconnect();
  settling = null;
  if (typeof MutationObserver !== "function" || !els.length) return;
  const watch = new MutationObserver((records) => {
    if (reduced()) return;
    for (const r of records) {
      for (const n of Array.from(r.addedNodes)) {
        // a closing pop-up's look-alike (smooth.ts) is on its way out: it never fades in
        if (n instanceof HTMLElement && n.isConnected && typeof n.animate === "function"
          && !n.classList.contains("leaving")) {
          n.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 220, easing: EASE });
        }
      }
    }
  });
  for (const el of els) {
    watch.observe(el, { childList: true, subtree: true });
    if (el.parentElement) watch.observe(el.parentElement, { childList: true });
  }
  settling = watch;
  window.setTimeout(() => {
    watch.disconnect();
    if (settling === watch) settling = null;
  }, SETTLE);
}

/**
 * What a change of tab changes on this page: everything after the tab bar it was made in, up to the page itself. That
 * bar is the last (innermost) one with links to both the address `before` and the one now shown, as with a second row
 * of tabs inside the first (Missions → Advanced's System, Jobs and Learning; the Brain's two Memory views); else the
 * first (outermost) one. A second row shows only on the pages it links to, so a change that brings one in comes from
 * a bar above it, and the new row fades in with the rest. The page's title and the bars above stay put. Empty when the
 * page has none.
 */
export function afterTabs(root: HTMLElement, before: string): HTMLElement[] {
  const navs = Array.from(root.querySelectorAll<HTMLElement>("nav.tabs, nav.brain-memory-views"));
  if (!navs.length) return [];
  const here = window.location.hash.split("?")[0];
  const links = (n: HTMLElement) => Array.from(n.querySelectorAll("a"), (a) => a.getAttribute("href"));
  const nav = navs.filter((n) => links(n).includes(here) && links(n).includes(before)).pop() || navs[0];
  const bar = nav.closest<HTMLElement>(".brain-tabs, .pub-bar, .settings-nav") || nav;
  const out: HTMLElement[] = [];
  for (let el: HTMLElement | null = bar; el && el !== root && !el.classList.contains("page"); el = el.parentElement) {
    for (let s = el.nextElementSibling; s; s = s.nextElementSibling) if (s instanceof HTMLElement) out.push(s);
  }
  return out;
}
