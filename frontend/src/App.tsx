import { KeyboardEvent as ReactKeyboardEvent, ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { errorText } from "./api";
import { ap } from "./autopilot";
import { Banner, ConnectionContext, Dialog, Icon, IconName, Logo, toast, ToastHost, useMenu } from "./components/ui";
import { leaveGuard, leaveTo, navigate, setLeaveAsker, useRoute, type Route } from "./router";
import { autopilotState, StatusProvider, useStatus } from "./status";
import { MotionProvider } from "./motion";
import { AppearanceProvider, useAppearance } from "./prefs";
import { installRequestProtection, loadMe, Me, signOut, SIGNED_OUT } from "./session";
import Office from "./pages/Office";
import Studio from "./pages/Studio";
import MakeClips from "./pages/MakeClips";
import MakeVideo from "./pages/MakeVideo";
import MakeShort from "./pages/MakeShort";
import VideoReview from "./pages/VideoReview";
import Customize from "./components/Customize";
import Projects from "./pages/Projects";
import Accounts from "./pages/Accounts";
import SignIn from "./pages/SignIn";
import Team, { RobotGallery } from "./pages/Team";
import Feedback from "./pages/Feedback";
import Brain from "./pages/Brain";
import Setup from "./pages/Setup";
import Create from "./pages/Create";
import ProjectView from "./pages/ProjectView";
import ClipEditor from "./pages/ClipEditor";
import PublishPage from "./pages/Publish";
import AutopilotPage from "./pages/Autopilot";
import Posts from "./pages/Posts";
import PostReview from "./pages/PostReview";
import SettingsPage from "./pages/Settings";

export { navigate };

// Studio combines Home and the Office (studio upgrade handoff, section 2); #/office is the Studio's expanded office.
type NavKey = "studio" | "projects" | "brain" | "publishing" | "accounts" | "settings";
const SECTION_NAV: Record<string, NavKey> = {
  "": "studio", create: "studio", projects: "projects", project: "projects", clip: "projects", publish: "projects",
  video: "projects", brain: "brain", publishing: "publishing", post: "publishing", accounts: "accounts",
  office: "studio", missions: "studio", setup: "studio", dev: "studio", settings: "settings",
};
const SECTION_TITLE: Record<string, string> = {
  "": "Studio", create: "Make", projects: "Projects", project: "Clips project", clip: "Edit clip", publish: "Prepare post",
  video: "Video", brain: "Brain", publishing: "Publishing", post: "Post review", accounts: "Accounts",
  office: "Studio · Office", missions: "Autopilot", setup: "Set up", dev: "Robot gallery", settings: "Settings",
};

function page(route: Route) {
  const [section, id] = route.parts;
  switch (section) {
    case "office": return id === "team" ? <Team /> : <Office />;
    case "dev": return <RobotGallery />;
    case "setup": return <Setup step={id} />;
    case "create": return id === "video" ? <MakeVideo /> : id === "short" ? <MakeShort /> : id === "transcript" ? <Create />
      : <MakeClips key={id || "clips"} initialInput={id === "link" ? "link" : "file"} />;
    case "projects": return id === "feedback" ? <Feedback /> : <Projects />;
    case "project": return <ProjectView id={id} key={id} />;
    case "clip": return <ClipEditor id={id} key={id} />;
    case "publish": return <PublishPage id={id} key={id} />;
    case "video": return <VideoReview id={id} key={id} />;
    case "missions": return <AutopilotPage tab={id} />;
    case "publishing": return <Posts view={id} />;
    case "post": return <PostReview id={id} key={id} />;
    case "accounts": return <Accounts />;
    case "settings": return <SettingsPage tab={id} />;
    case "brain": return <Brain tab={id} />;
    default: return <Studio />;
  }
}

installRequestProtection();

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [ended, setEnded] = useState(false);
  useEffect(() => {
    void loadMe().then(setMe);
    const out = () => setEnded(true);
    window.addEventListener(SIGNED_OUT, out);
    return () => window.removeEventListener(SIGNED_OUT, out);
  }, []);
  if (me === null) return null;  // nothing private is shown or requested before the session is known
  if ((me.mode === "cloud" && !me.signed_in) || ended) return <SignIn ended={ended} />;
  return (
    <AppearanceProvider>
      <MotionProvider>
        <StatusProvider><Shell me={me} /></StatusProvider>
      </MotionProvider>
    </AppearanceProvider>
  );
}

function Shell({ me }: { me: Me }) {
  const route = useRoute();
  const { namesVersion, customizing, setCustomizing } = useAppearance();
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem("clipforge.sidebar") === "collapsed";
    } catch {
      return false;
    }
  });
  const [makeOpen, setMakeOpen] = useState(false);
  const makeMenu = useMenu(makeOpen, setMakeOpen);
  const { st, lost, lastOk, refresh } = useStatus();
  const [drawer, setDrawer] = useState(false);
  // Where the person wanted to go when the page had unsaved changes ("" is the Office); null while nobody is asked.
  const [leaving, setLeaving] = useState<string | null>(null);
  const main = useRef<HTMLElement>(null);
  // The page whose title last got focus: none on first load (focus stays at the top, so Tab reaches the skip link),
  // and React's development double run of effects must not count as a move.
  const shown = useRef<string | null>(null);
  const section = route.parts[0] || "";
  const active = SECTION_NAV[section] || "studio";
  const wide = section === "office" && !route.parts[1];

  useEffect(() => {
    setLeaveAsker(setLeaving);
    return () => setLeaveAsker(null);
  }, []);

  // After moving to another page: the tab title, the top of the page, and focus on its title for screen readers.
  useLayoutEffect(() => {
    const title = SECTION_TITLE[section];
    document.title = title ? `${title} · ClipForge` : "ClipForge";
    setMakeOpen(false);
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
  const review = st?.home.posts?.review || 0;
  const fix = st?.home.posts?.fix || 0;
  const nav = (
    <>
      <NavLink href="#/" icon="home" label="Studio" on={active === "studio"} />
      <NavLink href="#/projects" icon="film" label="Projects" on={active === "projects"} />
      <NavLink href="#/brain/styles" icon="spark" label="Brain" on={active === "brain"} />
      <NavLink href="#/publishing/review" icon="posts" label="Publishing" on={active === "publishing"}
        extra={review ? <span className="count" title={`${review} waiting for your OK`}><span className="sr-only">, waiting for your OK: </span>{review}</span>
          : fix ? <span className="count bad" title={`${fix} need you to settle something`}><span className="sr-only">, need you: </span>{fix}</span> : null} />
      <NavLink href="#/accounts" icon="user" label="Accounts" on={active === "accounts"} />
      <NavLink href="#/settings/appearance" icon="settings" label="Settings" on={active === "settings"} />
    </>
  );
  const foot = (
    <div className="side-foot">
      <span>{me.mode === "cloud" ? "Your private ClipForge studio." : "Runs on this computer."} Uploads go only to the accounts and audience you choose.</span>
      <span className="legal-links">
        <a href="/legal/terms" target="_blank" rel="noreferrer">Terms</a> · <a href="/legal/privacy" target="_blank" rel="noreferrer">Privacy</a>
      </span>
    </div>
  );
  const brand = (
    <a className="brand" href="#/" aria-label="ClipForge, Studio">
      <Logo />
      <span className="brand-name" aria-hidden="true">ClipForge</span>
    </a>
  );
  const toggleSide = () => {
    setCollapsed((c) => {
      try {
        localStorage.setItem("clipforge.sidebar", c ? "open" : "collapsed");
      } catch {
        /* per-browser convenience only */
      }
      return !c;
    });
  };

  return (
    <ConnectionContext.Provider value={{ lost, lastOk }}>
      <a className="skip-link" href="#main" onClick={(e) => {
        e.preventDefault();
        main.current?.focus();
      }}>Skip to content</a>
      <div className={`cf-shell${collapsed ? " collapsed" : ""}`}>
        <aside className="cf-side" aria-label="ClipForge">
          {brand}
          <nav className="nav" aria-label="Main">{nav}</nav>
          <button type="button" className="btn btn-small btn-quiet" onClick={toggleSide} aria-pressed={collapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
            <Icon name="menu" /><span className="side-foot-label">{collapsed ? "" : "Collapse sidebar"}</span></button>
          {foot}
        </aside>
        <div className="cf-body">
          <header className="cf-top">
            <button type="button" className="btn btn-small menu-btn" aria-haspopup="dialog" aria-expanded={drawer} onClick={() => setDrawer(true)}>
              <Icon name="menu" />Menu
            </button>
            <p className="page-title">{SECTION_TITLE[section] || "ClipForge"}</p>
            <span className="spacer" />
            <div className="make-menu" ref={makeMenu.wrap} onKeyDown={makeMenu.onKey}>
              <button ref={makeMenu.button} type="button" className="btn btn-primary btn-small" aria-haspopup="menu"
                aria-expanded={makeOpen} onClick={() => setMakeOpen((o) => !o)}><Icon name="plus" />Make</button>
              {makeOpen && (
                <div role="menu" aria-label="Make">
                  <a role="menuitem" href="#/create/clips" onClick={() => setMakeOpen(false)}><b>Make clips</b><span>Highlights or full stories, vertical</span></a>
                  <a role="menuitem" href="#/create/video" onClick={() => setMakeOpen(false)}><b>Make a YouTube video</b><span>From your clips and four questions</span></a>
                  <a role="menuitem" href="#/create/short" onClick={() => setMakeOpen(false)}><b>Make an animated short</b><span>A voice-over short of moving pictures from your script, or one ClipForge AI writes</span></a>
                </div>
              )}
            </div>
            <button type="button" className="btn btn-small btn-icon" aria-label="Customize studio" title="Customize studio"
              aria-haspopup="dialog" aria-expanded={customizing} onClick={() => setCustomizing(true)}><Icon name="sliders" /></button>
            <a href="#/missions" id="top-state" className={`pill ${state.tone} hide-xs`} aria-label={`Autopilot: ${state.word}. Open Autopilot`}>
              <Icon name="autopilot" />Autopilot: {state.word}
            </a>
            {me.mode === "cloud" && <>
              <span className="who clamp-1" title={me.name}>{me.name}</span>
              <button type="button" className="btn btn-small" onClick={() => void signOut()}>Sign out</button>
            </>}
          </header>
          <main className={`main${wide ? " main-wide" : ""}`} id="main" ref={main} tabIndex={-1}>
            <div className="banners">
              {lost && (
                <Banner tone="warn" icon="offline" title="ClipForge is not answering"
                  actions={<button type="button" className="btn btn-small" onClick={refresh}><Icon name="refresh" />Try again</button>}>
                  What you see is the last known state{lastOk ? `, from ${new Date(lastOk).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : ""}.
                  {me.mode === "cloud" ? " Check your internet connection." : " Check that the ClipForge window is still open on this computer."}
                </Banner>
              )}
              {st?.paused && section !== "missions" && section !== "office" && (
                <Banner tone="bad" icon="stop" title="All jobs are stopped" actions={<ResumeButton onDone={refresh} />}>
                  Nothing is made, checked or posted until you resume. Things you start yourself wait too.
                </Banner>
              )}
              {route.unknown !== undefined && (
                <Banner tone="info" title="That address does not exist">
                  There is no page at “#/{route.unknown}”, so the Studio is shown instead.
                </Banner>
              )}
            </div>
            <div key={namesVersion} style={{ display: "contents" }}>{page(route)}</div>
          </main>
        </div>
      </div>
      {drawer && (
        <Drawer onClose={() => setDrawer(false)}>
          <div className="drawer-head">
            {brand}
            <button type="button" className="btn btn-small btn-icon" aria-label="Close menu" onClick={() => setDrawer(false)}><Icon name="x" /></button>
          </div>
          <nav className="nav" aria-label="Main">{nav}</nav>
          <div className="nav-sep" />
          {me.mode === "cloud" && <button type="button" className="btn" onClick={() => void signOut()}>Sign out</button>}
          {foot}
        </Drawer>
      )}
      {leaving !== null && <LeaveDialog target={leaving} onClose={() => setLeaving(null)} />}
      <Customize cloud={me.mode === "cloud"} />
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
