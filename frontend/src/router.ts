import { useEffect, useState } from "react";

/**
 * Addresses (design/ui-redesign/ROUTE_MAP.md). Old addresses keep working: they are replaced in place
 * (history.replaceState), so they open the new page and Back never bounces on them.
 */
const ALIASES: [RegExp, string][] = [
  [/^projects$/, "library"],
  [/^publish-center$/, "posts/review"],
  [/^publish-center\/upcoming$/, "posts/review"],
  [/^publish-center\/problems$/, "posts/problems"],
  [/^publish-center\/published$/, "posts/published"],
  [/^publish-center\/history$/, "posts/history"],
  [/^publish-center\/.*$/, "posts/review"],
  [/^posts$/, "posts/review"],
  [/^posts\/(?!(review|scheduled|published|history|problems|results)$).*$/, "posts/review"],
  [/^autopilot\/overview$/, "autopilot/system"],
  [/^autopilot\/(?!(activity|sources|system|jobs|learning)$).*$/, "autopilot"],
  [/^settings\/(?!(defaults|advanced)$).*$/, "settings"],
  [/^setup\/(?!(videos|mode|posting)$).*$/, "setup"],
];
const PAGES = ["", "create", "library", "project", "clip", "publish", "autopilot", "posts", "post", "setup", "settings"];
const NEEDS_ID = ["project", "clip", "publish", "post"];

export type Route = {
  /** The path after "#/", without a trailing slash ("posts/review"). */
  path: string;
  parts: string[];
  /** Set when the address did not exist, so Home is shown with a note. */
  unknown?: string;
};

function read(): Route {
  let path = decodeURIComponent(window.location.hash.replace(/^#\/?/, "")).replace(/\/+$/, "");
  for (const [re, to] of ALIASES) {
    if (re.test(path)) {
      history.replaceState(history.state, "", `#/${to}`);
      path = to;
      break;
    }
  }
  const parts = path.split("/").filter(Boolean);
  const first = parts[0] || "";
  if (!PAGES.includes(first) || (NEEDS_ID.includes(first) && !parts[1])) {
    return { path: "", parts: [], unknown: path };
  }
  return { path, parts };
}

/** Go to an address inside the app ("library", "#/clip/abc"). */
export function navigate(path: string) {
  window.location.hash = path.startsWith("#") ? path : `#/${path.replace(/^\/+/, "")}`;
}

// ------------------------------------------------------------------ unsaved changes
export type LeaveGuard = {
  /** What would be lost, in words ("Trim, Captions"). */
  what: string;
  /** Save, then leave. Resolves false (or throws) when saving did not work, so the page stays. */
  save?: () => Promise<boolean | void>;
  /** Forget the unsaved changes (the page's own state). */
  discard?: () => void;
};
let guard: LeaveGuard | null = null;
let onAsk: ((target: string) => void) | null = null;

/** While `g` is set, leaving the page (a link, Back, closing the window) asks first. */
export function useLeaveGuard(g: LeaveGuard | null) {
  useEffect(() => {
    guard = g;
    if (!g) return;
    const unload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", unload);
    return () => {
      window.removeEventListener("beforeunload", unload);
      if (guard === g) guard = null;
    };
  }, [g]);
}

export const leaveGuard = () => guard;
export const setLeaveAsker = (fn: ((target: string) => void) | null) => {
  onAsk = fn;
};

/** Leave after the person chose (Discard and leave, Save and leave): the guard no longer stops this one move. */
let passing: string | null = null;
/** A held-back Back or Forward: leaving repeats it (history.go) instead of adding an entry. */
let heldSteps = 0;
export function leaveTo(target: string) {
  guard = null;
  passing = target;
  if (heldSteps) history.go(heldSteps);
  else navigate(target);
  heldSteps = 0;
}

// ------------------------------------------------------------------ the current route
// Each history entry of the app carries its position, so a move the guard holds back can be undone exactly: a link
// (a new entry) is undone with Back, a Back or Forward with the opposite step. Rewriting the entry instead would
// leave a duplicate behind, and the next Back would seem to do nothing.
let position = 0;
const positionOf = (state: unknown) => (state as { cfPosition?: number } | null)?.cfPosition;
const mark = (n: number) => history.replaceState({ ...(history.state || {}), cfPosition: n }, "");

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => {
    if (!window.location.hash) history.replaceState(history.state, "", "#/");
    position = positionOf(history.state) ?? 0;
    mark(position);
    return read();
  });
  useEffect(() => {
    let current = route.path;
    let undoing = false;
    const change = () => {
      const known = positionOf(history.state);
      if (undoing) {
        // The step back to where the person was, after "Stay" or while they decide: nothing to show.
        undoing = false;
        position = known ?? position;
        return;
      }
      const next = read();
      const at = known ?? position + 1;
      if (guard && next.path !== current && passing !== next.path && onAsk) {
        // Undo the move (a link, Back or Forward) while the person decides; it happens only after they choose.
        undoing = true;
        heldSteps = known === undefined ? 0 : at - position;
        if (known === undefined) history.back();
        else history.go(position - at);
        onAsk(next.path);
        return;
      }
      passing = null;
      position = at;
      if (known === undefined) mark(at);
      current = next.path;
      setRoute(next);
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return route;
}
