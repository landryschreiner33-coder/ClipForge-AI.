import { useEffect, useState } from "react";
import { Icon, Logo, ToastHost } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import Create from "./pages/Create";
import Projects from "./pages/Projects";
import ProjectView from "./pages/ProjectView";
import ClipEditor from "./pages/ClipEditor";
import SettingsPage from "./pages/Settings";
import PublishPage from "./pages/Publish";
import AutopilotPage from "./pages/Autopilot";
import PublishCenter from "./pages/PublishCenter";

export function navigate(path: string) {
  window.location.hash = path;
}

function useRoute(): string[] {
  const read = () => (window.location.hash.replace(/^#\/?/, "") || "").split("/").filter(Boolean);
  const [parts, setParts] = useState(read);
  useEffect(() => {
    const h = () => {
      setParts(read());
      document.querySelector(".main")?.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  return parts;
}

const NAV = [
  { path: "", label: "Dashboard", icon: "dashboard" as const },
  { path: "create", label: "Create", icon: "create" as const },
  { path: "projects", label: "Projects", icon: "projects" as const },
  { path: "autopilot", label: "Autopilot", icon: "autopilot" as const },
  { path: "publish-center", label: "Publish Center", icon: "calendar" as const },
  { path: "settings", label: "Settings", icon: "settings" as const },
];

export default function App() {
  const parts = useRoute();
  const section = parts[0] || "";
  const activeNav = section === "project" || section === "clip" || section === "publish" ? "projects" : section;

  let page;
  if (section === "create") page = <Create />;
  else if (section === "projects") page = <Projects />;
  else if (section === "project" && parts[1]) page = <ProjectView id={parts[1]} key={parts[1]} />;
  else if (section === "clip" && parts[1]) page = <ClipEditor id={parts[1]} key={parts[1]} />;
  else if (section === "publish" && parts[1]) page = <PublishPage id={parts[1]} key={parts[1]} />;
  else if (section === "settings") page = <SettingsPage tab={parts[1]} />;
  else if (section === "autopilot") page = <AutopilotPage tab={parts[1]} />;
  else if (section === "publish-center") page = <PublishCenter view={parts[1]} />;
  else page = <Dashboard />;

  return (
    <div className="app">
      <aside className="sidebar">
        <a className="brand" href="#/">
          <Logo />
          <div className="brand-name">
            Clip<span>Foundry</span>
          </div>
        </a>
        {NAV.map((n) => (
          <a key={n.path} href={`#/${n.path}`} className={`nav-item ${activeNav === n.path ? "active" : ""}`}>
            <Icon name={n.icon} />
            <span>{n.label}</span>
          </a>
        ))}
        <div className="spacer" />
        <a href="#/create" className="btn primary block" style={{ marginBottom: 12 }}>
          <Icon name="spark" size={16} />
          <span className="nav-label">Create clips</span>
        </a>
        <div className="sidebar-foot">
          Runs on this computer.
          <br />
          No cloud rendering. Publishing is optional and uses the official APIs.
          <div className="legal-links">
            <a href="/legal/terms" target="_blank" rel="noreferrer">Terms</a> · <a href="/legal/privacy" target="_blank" rel="noreferrer">Privacy</a>
          </div>
        </div>
      </aside>
      <main className="main">{page}</main>
      <ToastHost />
    </div>
  );
}
