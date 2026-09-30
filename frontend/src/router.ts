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
let passing = "";
export function leaveTo(target: string) {
  guard = null;
  passing = target;
  navigate(target);
}

// ------------------------------------------------------------------ the current route
export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => {
    if (!window.location.hash) history.replaceState(history.state, "", "#/");
    return read();
  });
  useEffect(() => {
    let current = route.path;
    const change = () => {
      const next = read();
      if (guard && next.path !== current && passing !== next.path && onAsk) {
        // Undo the move (a link or Back) while the person decides; it happens only after they choose.
        history.replaceState(history.state, "", `#/${current}`);
        onAsk(next.path);
        return;
      }
      passing = "";
      current = next.path;
      setRoute(next);
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return route;
}
