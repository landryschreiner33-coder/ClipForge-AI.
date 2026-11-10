import { useEffect, useState } from "react";

/**
 * Addresses (docs/clipforge/ROUTE_MAP.md). Old addresses keep working: they are replaced in place
 * (history.replaceState), so they open the new page and Back never bounces on them.
 */
const POSTS = "(review|scheduled|published|history|problems|results)";
const MISSIONS = "(activity|sources|system|jobs|learning)";
const ALIASES: [RegExp, string][] = [
  // ClipForge places (docs/clipforge/ROUTE_MAP.md): Studio, Projects, Brain, Publishing, Accounts, Settings.
  // Studio is Home and the Office together; #/office is its expanded office and #/office/team the Team list.
  [/^(home|studio)$/, ""],
  [/^studio\/office$/, "office"],
  [/^studio\/team$/, "office/team"],
  [/^office\/(?!team$).*$/, "office"],
  [/^clips\/feedback$/, "projects/feedback"],
  [/^(clips|library)(\/.*)?$/, "projects"],
  [/^projects\/(?!feedback$).+$/, "projects"],
  [/^publish-center\/problems$/, "publishing/problems"],
  [/^publish-center\/published$/, "publishing/published"],
  [/^publish-center\/history$/, "publishing/history"],
  [/^publish-center(\/.*)?$/, "publishing/review"],
  [new RegExp(`^(posts|queue)/${POSTS}$`), "publishing/$2"],
  [/^(posts|queue)(\/.*)?$/, "publishing/review"],
  [new RegExp(`^publishing(?!/${POSTS}$).*$`), "publishing/review"],
  [/^autopilot\/overview$/, "missions/system"],
  [new RegExp(`^autopilot/${MISSIONS}$`), "missions/$1"],
  [/^autopilot(\/.*)?$/, "missions"],
  [new RegExp(`^missions/(?!${MISSIONS}$).*$`), "missions"],
  [/^create$/, "create/clips"],
  [/^create\/(?!(clips|video|short|link|transcript)$).*$/, "create/clips"],
  [/^settings\/accounts$/, "accounts"],
  [/^settings\/(?!(appearance|media|ai|apps|makers|defaults|integrations|advanced)$).*$/, "settings"],
  [/^setup\/(?!(videos|mode|posting)$).*$/, "setup"],
  [/^dev(\/(?!robots$).*)?$/, "dev/robots"],
];
const PAGES = ["", "office", "missions", "projects", "publishing", "create", "project", "clip", "publish", "post", "setup",
  "settings", "brain", "dev", "accounts", "video"];
const NEEDS_ID = ["project", "clip", "publish", "post", "video"];

export type Route = {
  /** The path after "#/", without a trailing slash ("posts/review"). */
  path: string;
  parts: string[];
  /** Set when the address did not exist, so the Studio is shown with a note. */
  unknown?: string;
};

function read(): Route {
  let path = decodeURIComponent(window.location.hash.replace(/^#\/?/, "")).replace(/\/+$/, "");
  for (const [re, to] of ALIASES) {
    if (re.test(path)) {
      const next = path.replace(re, to);
      if (next === path) break;  // already the current address (queue/review matches its own alias)
      history.replaceState(history.state, "", `#/${next}`);
      path = next;
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
/** A held-back Back or Forward: leaving to where it led repeats it (history.go) instead of adding an entry. */
let held: { steps: number; path: string } | null = null;
export function leaveTo(target: string) {
  guard = null;
  passing = target.replace(/^#?\/?/, "").replace(/\/+$/, "");
  if (held && held.path === passing) history.go(held.steps);
  else navigate(target);
  held = null;
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
        held = known === undefined ? null : { steps: at - position, path: next.path };
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
