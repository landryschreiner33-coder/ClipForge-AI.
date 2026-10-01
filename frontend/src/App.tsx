import { KeyboardEvent as ReactKeyboardEvent, ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { errorText } from "./api";
import { ap } from "./autopilot";
import { Banner, ConnectionContext, Dialog, Icon, IconName, Logo, toast, ToastHost } from "./components/ui";
import { leaveGuard, leaveTo, navigate, setLeaveAsker, useRoute, type Route } from "./router";
import { autopilotState, StatusProvider, useStatus } from "./status";
import Home from "./pages/Home";
import Setup from "./pages/Setup";
import Create from "./pages/Create";
import Library from "./pages/Library";
import ProjectView from "./pages/ProjectView";
import ClipEditor from "./pages/ClipEditor";
import PublishPage from "./pages/Publish";
import AutopilotPage from "./pages/Autopilot";
import Posts from "./pages/Posts";
import PostReview from "./pages/PostReview";
import SettingsPage from "./pages/Settings";

export { navigate };

type NavKey = "home" | "autopilot" | "library" | "posts" | "settings";
const SECTION_NAV: Record<string, NavKey> = {
  "": "home", setup: "home", autopilot: "autopilot", library: "library", project: "library", clip: "library",
  publish: "library", create: "library", posts: "posts", post: "posts", settings: "settings",
};
const SECTION_TITLE: Record<string, string> = {
  "": "", setup: "Set up", autopilot: "Autopilot", library: "Library", project: "Source video", clip: "Edit clip",
  publish: "Prepare post", create: "Add video", posts: "Posts", post: "Post review", settings: "Settings",
};

function page(route: Route) {
  const [section, id] = route.parts;
  switch (section) {
    case "setup": return <Setup step={id} />;
    case "create": return <Create />;
    case "library": return <Library />;
    case "project": return <ProjectView id={id} key={id} />;
    case "clip": return <ClipEditor id={id} key={id} />;
    case "publish": return <PublishPage id={id} key={id} />;
    case "autopilot": return <AutopilotPage tab={id} />;
    case "posts": return <Posts view={id} />;
    case "post": return <PostReview id={id} key={id} />;
    case "settings": return <SettingsPage tab={id} />;
    default: return <Home />;
  }
}

export default function App() {
  return (
    <StatusProvider>
      <Shell />
    </StatusProvider>
  );
}

function Shell() {
  const route = useRoute();
  const { st, lost, lastOk, refresh } = useStatus();
  const [drawer, setDrawer] = useState(false);
  // Where the person wanted to go when the page had unsaved changes ("" is Home); null while nobody is asked.
  const [leaving, setLeaving] = useState<string | null>(null);
  const main = useRef<HTMLElement>(null);
  // The page whose title last got focus: none on first load (focus stays at the top, so Tab reaches the skip link),
  // and React's development double run of effects must not count as a move.
  const shown = useRef<string | null>(null);
  const section = route.parts[0] || "";
  const active = SECTION_NAV[section] || "home";

  useEffect(() => {
    setLeaveAsker(setLeaving);
    return () => setLeaveAsker(null);
  }, []);

  // After moving to another page: the tab title, the top of the page, and focus on its title for screen readers.
  useLayoutEffect(() => {
    const title = SECTION_TITLE[section];
    document.title = title ? `${title} · ClipFoundry` : "ClipFoundry";
    setDrawer(false);
    const key = `${route.path}|${route.unknown ?? ""}`;
    const first = shown.current === null;
    if (first || shown.current === key) {
      shown.current = key;
      return;
    }
    shown.current = key;
    window.scrollTo(0, 0);
    const focus = () => {
      const h1 = main.current?.querySelector<HTMLElement>("h1");
      if (!h1) return false;
      h1.focus({ preventScroll: true });
      return true;
    };
    if (focus()) return;
    const watch = new MutationObserver(() => focus() && watch.disconnect());
    watch.observe(main.current!, { childList: true, subtree: true });
    const stop = setTimeout(() => watch.disconnect(), 4000);
    return () => {
      watch.disconnect();
      clearTimeout(stop);
    };
  }, [route.path, route.unknown, section]);

  const state = autopilotState(st, lost);
  const tone = state.tone === "good" ? "on" : state.tone === "neutral" ? "" : state.tone;
  const review = st?.home.posts?.review || 0;
  const fix = st?.home.posts?.fix || 0;
  const nav = (
    <>
      <NavLink href="#/" icon="home" label="Home" on={active === "home"} />
      <NavLink href="#/autopilot" icon="autopilot" label="Autopilot" on={active === "autopilot"}
        extra={<span className={`state ${tone}`}><span className="sr-only">: </span>{state.word}</span>} />
      <NavLink href="#/library" icon="library" label="Library" on={active === "library"} />
      <NavLink href="#/posts/review" icon="posts" label="Posts" on={active === "posts"}
        extra={review ? <span className="count" title={`${review} waiting for your OK`}><span className="sr-only">, waiting for your OK: </span>{review}</span>
          : fix ? <span className="count bad" title={`${fix} need you to settle something`}><span className="sr-only">, need you: </span>{fix}</span> : null} />
    </>
  );
  const settingsLink = <NavLink href="#/settings" icon="settings" label="Settings" on={active === "settings"} />;
  const foot = (
    <div className="sidebar-foot">
      <span>Runs on this computer. Posting is optional and uses YouTube's and TikTok's official connections.</span>
      <span className="legal-links">
        <a href="/legal/terms" target="_blank" rel="noreferrer">Terms</a> · <a href="/legal/privacy" target="_blank" rel="noreferrer">Privacy</a>
      </span>
    </div>
  );
  const brand = (
    <a className="brand" href="#/" aria-label="ClipFoundry, Home">
      <Logo />
      <span className="brand-name" aria-hidden="true">Clip<span>Foundry</span></span>
    </a>
  );

  return (
    <ConnectionContext.Provider value={{ lost, lastOk }}>
      <a className="skip-link" href="#main" onClick={(e) => {
        e.preventDefault();
        main.current?.focus();
      }}>Skip to content</a>
      <header className="topbar">
        <button type="button" className="btn btn-small" aria-haspopup="dialog" aria-expanded={drawer} onClick={() => setDrawer(true)}>
          <Icon name="menu" />Menu
        </button>
        {brand}
        <span className="spacer" />
        <a href="#/autopilot" id="top-state" className={`pill ${state.tone}`}>
          <Icon name="autopilot" />Autopilot: {state.word}
        </a>
      </header>
      <div className="app">
        <aside className="sidebar">
          {brand}
          <nav className="nav" aria-label="Main">{nav}</nav>
          <div className="nav-sep" />
          <nav className="nav" aria-label="Settings">{settingsLink}</nav>
          {foot}
        </aside>
        <main className="main" id="main" ref={main} tabIndex={-1}>
          <div className="banners">
            {lost && (
              <Banner tone="warn" icon="offline" title="ClipFoundry is not answering"
                actions={<button type="button" className="btn btn-small" onClick={refresh}><Icon name="refresh" />Try again</button>}>
                What you see is the last known state{lastOk ? `, from ${new Date(lastOk).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : ""}.
                Check that the black ClipFoundry window is still open on this PC.
              </Banner>
            )}
            {st?.paused && section !== "autopilot" && (
              <Banner tone="bad" icon="stop" title="All jobs are stopped" actions={<ResumeButton onDone={refresh} />}>
                Nothing is made, checked or posted until you resume. Things you start yourself wait too.
              </Banner>
            )}
            {route.unknown !== undefined && (
              <Banner tone="info" title="That address does not exist">
                There is no page at “#/{route.unknown}”, so Home is shown instead.
              </Banner>
            )}
          </div>
          {page(route)}
        </main>
      </div>
      {drawer && (
        <Drawer onClose={() => setDrawer(false)}>
          <div className="drawer-head">
            {brand}
            <button type="button" className="btn btn-small btn-icon" aria-label="Close menu" onClick={() => setDrawer(false)}><Icon name="x" /></button>
          </div>
          <nav className="nav" aria-label="Main">{nav}</nav>
          <nav className="nav" aria-label="Settings">{settingsLink}</nav>
          <div className="nav-sep" />
          {foot}
        </Drawer>
      )}
      {leaving !== null && <LeaveDialog target={leaving} onClose={() => setLeaving(null)} />}
      <ToastHost />
    </ConnectionContext.Provider>
  );
}

function NavLink({ href, icon, label, on, extra }: { href: string; icon: IconName; label: string; on: boolean; extra?: ReactNode }) {
  return (
    <a href={href} className={`nav-item ${on ? "active" : ""}`} aria-current={on ? "page" : undefined}>
      <Icon name={icon} />
      <span>{label}</span>
      {extra}
    </a>
  );
}

function ResumeButton({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <button type="button" className="btn btn-small" disabled={busy} onClick={async () => {
      setBusy(true);
      try {
        await ap.resume();
        toast("Jobs can run again");
      } catch (e) {
        toast(errorText(e), true);
      }
      setBusy(false);
      onDone();
    }}><Icon name="play" />Resume jobs</button>
  );
}

/** The menu on small windows: a dialog, so focus stays inside and Escape closes it. */
function Drawer({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>('[aria-current="page"], a, button')?.focus();
    return () => {
      if (opener && document.contains(opener)) opener.focus();
    };
  }, []);
  const onKey = (e: ReactKeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
    }
    if (e.key !== "Tab") return;
    const items = Array.from(ref.current!.querySelectorAll<HTMLElement>("a[href], button:not([disabled])"));
    const [a, z] = [items[0], items[items.length - 1]];
    if (e.shiftKey && document.activeElement === a) {
      e.preventDefault();
      z.focus();
    } else if (!e.shiftKey && document.activeElement === z) {
      e.preventDefault();
      a.focus();
    }
  };
  return (
    <>
      <div className="drawer-bg" onMouseDown={onClose} />
      <div ref={ref} className="drawer" role="dialog" aria-modal="true" aria-label="Menu" onKeyDown={onKey}>
        {children}
      </div>
    </>
  );
}

/** Leaving a page with unsaved changes (a link, Back): Stay, Discard and leave, or Save and leave. */
function LeaveDialog({ target, onClose }: { target: string; onClose: () => void }) {
  const g = leaveGuard();
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!g) onClose();
  }, [g, onClose]);
  if (!g) return null;
  const save = async () => {
    setBusy(true);
    try {
      const ok = await g.save!();
      if (ok === false) {
        setBusy(false);
        return;
      }
      onClose();
      leaveTo(target);
    } catch (e) {
      toast(errorText(e), true);
      setBusy(false);
    }
  };
  return (
    <Dialog title="Leave without saving?" onClose={onClose} actions={<>
      <button type="button" className="btn btn-quiet" onClick={onClose} data-autofocus>Stay</button>
      <button type="button" className="btn btn-danger" disabled={busy} onClick={() => {
        g.discard?.();
        onClose();
        leaveTo(target);
      }}>Discard and leave</button>
      {g.save && <button type="button" className="btn btn-primary" disabled={busy} onClick={save}>Save and leave</button>}
    </>}>
      <p className="muted">You changed {g.what}. If you leave now, those changes are lost.</p>
    </Dialog>
  );
}
